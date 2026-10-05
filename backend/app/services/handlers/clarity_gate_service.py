"""Zone transition Clarity Gate — LLM evaluation grounded in full Zone whiteboard teaching."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.constants import CLARITY_GATE_PASS_THRESHOLD
from app.services.handlers.cluster_teachback_service import (
    _display_point,
    _teachback_coverage_prompt_block,
    _teachback_lesson_block,
    teachback_coverage_from_ctx,
)
from app.services.handlers.concept_check_question_service import _parse_json_object
from app.services.handlers.teaching_transcript_service import (
    build_zone_clarity_gate_taught_context,
)

if TYPE_CHECKING:
    from beanie.odm.fields import PydanticObjectId

    from app.models.learning.sessions import Session

logger = logging.getLogger(__name__)


async def resolve_clarity_gate_taught_context(
    session: Session,
    session_id: PydanticObjectId,
) -> dict[str, Any]:
    """Full Zone 1 whiteboard context — all clusters taught in this session."""
    return await build_zone_clarity_gate_taught_context(session_id, session)


async def build_clarity_gate_eval_context(
    session: Session,
    session_id: PydanticObjectId,
    *,
    question: str,
    gate_concepts: list[str],
) -> str:
    taught_ctx = await resolve_clarity_gate_taught_context(session, session_id)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    taught_block = _teachback_lesson_block(taught_ctx)
    labels = [
        _display_point(p)
        for p in coverage.get("coverage_labels") or []
        if _display_point(p)
    ]
    facts = [
        _display_point(p)
        for p in coverage.get("coverage_facts") or []
        if _display_point(p)
    ]
    concepts = [_display_point(c) for c in gate_concepts if _display_point(c)]
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    parts = [
        f"CLARITY GATE QUESTION ASKED TO THE STUDENT:\n{question.strip()}",
    ]
    if concepts:
        parts.append("ZONE CONCEPTS: " + "; ".join(concepts))
    coverage_block = _teachback_coverage_prompt_block(coverage)
    if coverage_block:
        parts.append(coverage_block)
    elif labels or facts:
        required = labels or facts
        parts.append(
            "REQUIRED COVERAGE — student should connect ALL taught ideas "
            f"({len(required)} items): {'; '.join(required)}"
        )
    if topic_anchor:
        parts.append(
            f'TOPIC CONTEXT (umbrella label only — not a separate item): "{topic_anchor}"'
        )
    if taught_block:
        parts.append(
            "AUTHORITATIVE — grade ONLY against what was taught on the whiteboard "
            "across the full zone:\n"
            + taught_block
        )
    return "\n\n".join(parts).strip()


async def evaluate_clarity_gate_answer(
    session: Session,
    session_id: PydanticObjectId,
    *,
    student_answer: str,
    question: str,
    gate_concepts: list[str],
) -> dict[str, Any]:
    """LLM evaluation with the same grounding model as cluster teachback."""
    from app.services.evaluation_engine import clean_context, evaluate_answer
    from app.services.rag_service import RAGService
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository

    gate_concepts = [str(c).strip() for c in gate_concepts if str(c).strip()]
    taught_ctx = await resolve_clarity_gate_taught_context(session, session_id)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    required_labels = list(coverage.get("coverage_labels") or [])
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    required_count = int(coverage.get("coverage_count") or len(required_labels) or 0)
    reference = await build_clarity_gate_eval_context(
        session,
        session_id,
        question=question,
        gate_concepts=gate_concepts,
    )
    context_block = clean_context(reference) or ""

    eval_targets = required_labels or gate_concepts
    if not (student_answer or "").strip():
        return {
            "score": 0,
            "correct": False,
            "feedback": "Please share your explanation in your own words.",
            "missing_points": eval_targets,
            "score_rationale": "There was no answer to evaluate.",
            "ideal_answer": "",
        }

    concepts_str = ", ".join(f'"{c}"' for c in gate_concepts) if gate_concepts else "(zone)"
    coverage_line = ""
    if required_labels:
        coverage_line = (
            f"\nREQUIRED TAUGHT IDEAS ({required_count}): "
            + "; ".join(_display_point(l) for l in required_labels)
        )
    topic_line = ""
    if topic_anchor:
        topic_line = (
            f'\nTOPIC CONTEXT: "{topic_anchor}" is the umbrella topic — grading is on '
            f"the taught characteristics below, NOT on restating the topic title alone."
        )

    prompt = f"""\
You are an expert, empathetic tutor evaluating a student's ZONE synthesis teachback.

CLARITY GATE QUESTION:
{question.strip()}

ZONE CONCEPTS: {concepts_str}{coverage_line}{topic_line}

STUDENT ANSWER:
{student_answer.strip()}

EVALUATION RULES:
1. Grade MEANING and understanding — not exact wording.
2. Compare ONLY to the authoritative whiteboard lesson content in the context below.
3. The student must connect ideas taught across ALL clusters in this zone.
4. Paraphrases and informal language count when the idea is right.
5. The topic anchor/title alone does NOT count as covering a taught characteristic.
6. score_rationale must briefly say WHY you chose that number (1–2 sentences).
7. missing_points must list specific taught ideas the answer did not cover.

SCORING GUIDE:
  {CLARITY_GATE_PASS_THRESHOLD}–100 : Strong zone synthesis — covers taught ideas well.
  40–{CLARITY_GATE_PASS_THRESHOLD - 1} : Partial — some key ideas present, gaps remain.
  0–39   : Weak — major gaps or misconceptions.

Respond ONLY with valid JSON (no markdown):
{{"score": <int 0-100>, "score_rationale": "<why this score>", "feedback": "<warm 1-2 sentences>", "missing_points": ["<gap>"], "ideal_answer": "<correct zone summary from lesson>"}}"""

    rag_service = RAGService(
        TopicNoteRepository(),
        VideoSubtitleRepository(),
        TopicQuestionRepository(),
        TopicRepository(),
    )
    try:
        raw = await rag_service.generate_prompt(
            question=prompt,
            context=context_block,
            student_profile=None,
            topic_name=None,
            learning_state="teachback",
            user_intent="EVALUATION",
            current_concept="zone_clarity_gate",
        )
        data = _parse_json_object(raw or "")
        if data:
            score = int(data.get("score", 0) or 0)
            score = max(0, min(100, score))
            missing = [
                str(m).strip()
                for m in (data.get("missing_points") or [])
                if str(m).strip()
            ]
            return {
                "score": score,
                "correct": score >= CLARITY_GATE_PASS_THRESHOLD,
                "feedback": str(data.get("feedback") or "").strip(),
                "missing_points": missing or eval_targets,
                "score_rationale": str(data.get("score_rationale") or "").strip(),
                "ideal_answer": str(data.get("ideal_answer") or "").strip(),
            }
    except Exception:
        logger.exception("[CLARITY_GATE] LLM evaluation failed — rule fallback")

    base = await evaluate_answer(eval_targets or ["zone"], student_answer, reference)
    score = int(base.get("score", 0) or 0)
    return {
        **base,
        "score": score,
        "score_rationale": str(base.get("feedback") or "").strip(),
        "ideal_answer": "",
    }
