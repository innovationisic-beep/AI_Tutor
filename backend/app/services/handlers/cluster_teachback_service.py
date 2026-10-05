"""
Cluster-end teachback: one comprehensive grounded question + evaluation context.

After cluster quiz the student explains the full cluster in their own words.
The question must reference only what was taught (cluster_taught_points + timeline).

Scoring tiers (LLM, 0–100):
  >=80 — appreciate + restate correct answer → advance
  50–79 — up to 2 Socratic probes → simple ideal-answer explanation → advance
  <50  — empathetic intro + simplified VTSE re-teach → new teachback question → retry
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.core.constants import (
    CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD,
    CLUSTER_TEACHBACK_PARTIAL_THRESHOLD,
)
from app.services.handlers.concept_check_question_service import _parse_json_object
from app.services.handlers.concept_taught_context import (
    format_grading_context_block,
    question_count_matches_taught,
)
from app.services.handlers.teaching_transcript_service import (
    build_cluster_quiz_taught_context,
    format_transcript_taught_block,
)

if TYPE_CHECKING:
    from beanie.odm.fields import PydanticObjectId

    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)

_BROAD_ONLY_RE = re.compile(
    r"(?i)\b(how do (these|they) connect|walk me through how|main ideas? connect)\b"
)


def _display_point(point: str) -> str:
    return str(point or "").strip().replace("_", " ")


def _cluster_topic_label(concepts: list[str]) -> str:
    concepts = [str(c).strip() for c in concepts if str(c).strip()]
    if len(concepts) == 1:
        return concepts[0]
    if len(concepts) == 2:
        return f"{concepts[0]} and {concepts[1]}"
    if concepts:
        return ", ".join(concepts[:-1]) + f", and {concepts[-1]}"
    return "this topic"


def teachback_coverage_from_ctx(taught_ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Quizable teachback coverage — hierarchy topic anchor is context only.

    Returns coverage_facts (full explanations), coverage_labels (short names),
    and topic_anchor (umbrella label, not a separate required item).
    """
    topic_anchor = str(taught_ctx.get("topic_anchor") or "").strip()
    facts = [
        str(f).strip()
        for f in (taught_ctx.get("teaching_facts") or [])
        if str(f).strip()
    ]
    steps = [
        str(s).strip() for s in (taught_ctx.get("steps") or []) if str(s).strip()
    ]

    if facts:
        return {
            "topic_anchor": topic_anchor,
            "coverage_facts": facts,
            "coverage_labels": steps or facts,
            "coverage_count": len(facts),
        }

    raw = [
        str(p).strip()
        for p in (taught_ctx.get("taught_points") or taught_ctx.get("steps") or [])
        if str(p).strip()
    ]
    topic_low = topic_anchor.lower()
    filtered: list[str] = []
    for point in raw:
        pl = _display_point(point).lower()
        if topic_low and pl == topic_low:
            continue
        filtered.append(_display_point(point))

    return {
        "topic_anchor": topic_anchor,
        "coverage_facts": filtered,
        "coverage_labels": filtered,
        "coverage_count": len(filtered),
    }


async def resolve_cluster_teachback_taught_context(
    session: Session,
    session_id: PydanticObjectId,
) -> dict[str, Any]:
    """Authoritative cluster lesson context — same timeline-aware path as cluster quiz."""
    return await build_cluster_quiz_taught_context(session_id, session)


def _teachback_lesson_block(taught_ctx: dict[str, Any]) -> str:
    block = format_transcript_taught_block(taught_ctx)
    if block:
        return block
    return format_grading_context_block(taught_ctx)


def _teachback_coverage_prompt_block(coverage: dict[str, Any]) -> str:
    topic = str(coverage.get("topic_anchor") or "").strip()
    labels = list(coverage.get("coverage_labels") or [])
    facts = list(coverage.get("coverage_facts") or [])
    count = int(coverage.get("coverage_count") or 0)

    if not labels and not facts:
        return ""

    lines: list[str] = []
    if topic:
        lines.append(
            f'TOPIC CONTEXT: "{topic}" (umbrella label only — do NOT treat as a '
            f"separate characteristic the student must explain)"
        )
    if labels:
        lines.append(
            f"CHARACTERISTICS TO EXPLAIN (exactly {count or len(labels)} — "
            f"student must cover ALL of these):"
        )
        for i, label in enumerate(labels):
            detail = facts[i] if i < len(facts) else label
            lines.append(f"- {label}: {detail}")
    elif facts:
        lines.append(
            f"TAUGHT POINTS (student must explain all {len(facts)}):"
        )
        lines.extend(f"- {f}" for f in facts)

    if topic and count:
        lines.append(
            f"\nRULES: Ask the student to explain exactly {count} characteristics "
            f'under "{topic}", not {count + 1}. The topic name itself is NOT one '
            f"of the characteristics."
        )
    return "\n".join(lines)


def fallback_cluster_teachback_question(
    concepts: list[str],
    coverage_labels: list[str],
    *,
    topic_anchor: str = "",
    coverage_facts: list[str] | None = None,
) -> str:
    """Deterministic long teachback question grounded in taught characteristics."""
    topic = topic_anchor.strip() or _cluster_topic_label(concepts)
    labels = [_display_point(p) for p in coverage_labels if _display_point(p)]
    facts = [_display_point(p) for p in (coverage_facts or []) if _display_point(p)]

    if not labels and facts:
        labels = facts

    if not labels:
        return (
            f"In your own words, explain everything we learned about {topic} in this cluster. "
            f"Cover all the main ideas from the lesson and briefly explain each."
        )

    if len(labels) == 1:
        detail = facts[0] if facts else labels[0]
        return (
            f"In your own words, explain {topic}. "
            f"Describe what we learned about {labels[0]} ({detail}) "
            f"and briefly explain what it means."
        )

    named = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    return (
        f"In your own words, explain {topic}. "
        f"Describe all {len(labels)} characteristics we covered ({named}) "
        f"and briefly explain what each one means."
    )


def _question_covers_taught_points(question: str, taught_points: list[str]) -> bool:
    q_low = (question or "").lower()
    if not taught_points:
        return len(q_low) >= 40
    hits = 0
    for point in taught_points:
        disp = _display_point(point).lower()
        if not disp:
            continue
        tokens = [w for w in re.findall(r"[a-z]{4,}", disp) if len(w) >= 4]
        if disp in q_low or any(t in q_low for t in tokens):
            hits += 1
            continue
        if len(tokens) == 1 and tokens[0] in q_low:
            hits += 1
    if len(taught_points) <= 2:
        return hits >= 1
    return hits >= max(1, len(taught_points) // 2)


def validate_cluster_teachback_question(
    question: str,
    taught_ctx: dict[str, Any],
    coverage_labels: list[str],
) -> bool:
    q = (question or "").strip()
    if len(q) < 48:
        return False
    if _BROAD_ONLY_RE.search(q) and not _question_covers_taught_points(q, coverage_labels):
        return False
    if not question_count_matches_taught(q, taught_ctx):
        return False
    if coverage_labels and not _question_covers_taught_points(q, coverage_labels):
        return False
    topic = str(taught_ctx.get("topic_anchor") or "").strip().lower()
    if topic and coverage_labels:
        q_low = q.lower()
        label_hits = sum(
            1 for label in coverage_labels if _display_point(label).lower() in q_low
        )
        if label_hits < max(1, len(coverage_labels) // 2):
            return False
    return True


async def build_cluster_teachback_eval_context(
    session: Session,
    session_id: PydanticObjectId,
    question: str,
) -> str:
    """Reference context for LLM evaluation — question + authoritative taught content."""
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
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
    concepts = [
        str(c).strip()
        for c in (getattr(session, "teachback_concepts", None) or [])
        if str(c).strip()
    ]
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    parts = [
        f"TEACHBACK QUESTION ASKED TO THE STUDENT:\n{question.strip()}",
    ]
    if concepts:
        parts.append("CLUSTER CONCEPTS: " + "; ".join(concepts))
    if topic_anchor:
        parts.append(
            f'TOPIC CONTEXT (not a separate required item): "{topic_anchor}"'
        )
    if labels or facts:
        required = labels or facts
        parts.append(
            "REQUIRED COVERAGE — student should explain each CHARACTERISTIC below "
            f"with a brief explanation ({len(required)} items, not including the "
            f"topic title alone): {'; '.join(required)}"
        )
        if facts and facts != labels:
            parts.append(
                "DETAIL FOR EACH CHARACTERISTIC:\n"
                + "\n".join(f"- {f}" for f in facts)
            )
    if taught_block:
        parts.append(
            "AUTHORITATIVE — grade ONLY against what was taught in this lesson:\n"
            + taught_block
        )
    return "\n\n".join(parts).strip()


def cluster_teachback_tier(score: float) -> str:
    """Return excellent | partial | weak for a 0–100 teachback score."""
    s = float(score or 0)
    if s >= CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD:
        return "excellent"
    if s >= CLUSTER_TEACHBACK_PARTIAL_THRESHOLD:
        return "partial"
    return "weak"


def format_score_announcement(
    score: int,
    score_rationale: str,
    *,
    prefix: str = "",
) -> str:
    """Transparent score line the tutor speaks to the student."""
    rationale = (score_rationale or "").strip()
    line = f"I'm giving your answer **{score} out of 100**."
    if rationale:
        line += f" {rationale}"
    if prefix:
        return f"{prefix.strip()}\n\n{line}"
    return line


def format_excellent_teachback_message(eval_res: dict[str, Any]) -> str:
    score = int(eval_res.get("score", 0) or 0)
    rationale = str(eval_res.get("score_rationale") or "").strip()
    feedback = str(eval_res.get("feedback") or "").strip()
    ideal = str(
        eval_res.get("ideal_answer")
        or eval_res.get("correct_answer_summary")
        or ""
    ).strip()
    parts = [
        format_score_announcement(score, rationale),
        "Excellent work — you really understood this cluster!",
    ]
    if feedback and feedback.lower() not in rationale.lower():
        parts.append(feedback)
    if ideal:
        parts.append(f"Just to reinforce: {ideal}")
    return "\n\n".join(parts)


def format_partial_start_message(eval_res: dict[str, Any], socratic_question: str) -> str:
    score = int(eval_res.get("score", 0) or 0)
    rationale = str(eval_res.get("score_rationale") or "").strip()
    intro = format_score_announcement(
        score,
        rationale,
        prefix=(
            "You're on the right track, but let's sharpen a few ideas together."
        ),
    )
    q = (socratic_question or "").strip()
    if q and not q.endswith("?"):
        q = f"{q.rstrip('.')}?"
    return f"{intro}\n\n{q}"


def format_weak_teachback_intro(eval_res: dict[str, Any]) -> str:
    """Empathetic intro before simplified VTSE re-teach (score + encouragement)."""
    score = int(eval_res.get("score", 0) or 0)
    rationale = str(eval_res.get("score_rationale") or "").strip()
    return format_score_announcement(
        score,
        rationale,
        prefix=(
            "I think you haven't quite got what I was teaching — and that's "
            "completely okay. You seem a bit confused, so let me teach you this "
            "cluster again, more simply."
        ),
    )


def format_weak_teachback_message(
    eval_res: dict[str, Any],
    *,
    reteach_text: str,
    new_question: str,
) -> str:
    """Fallback when simplified VTSE is unavailable — prose re-teach + new question."""
    parts = [format_weak_teachback_intro(eval_res)]
    if (reteach_text or "").strip():
        parts.append(reteach_text.strip())
    q = (new_question or "").strip()
    if q:
        parts.append(f"When you're ready, try again in your own words:\n\n{q}")
    return "\n\n".join(parts)


def format_socratic_followup_message(socratic_question: str) -> str:
    q = (socratic_question or "").strip()
    if q and not q.endswith("?"):
        q = f"{q.rstrip('.')}?"
    return q or "What else from this cluster can you explain in your own words?"


def format_post_socratic_explanation_message(simple_ideal_explanation: str) -> str:
    """After 2 Socratic probes — plain-language model answer (no VTSE re-teach)."""
    parts: list[str] = []
    text = (simple_ideal_explanation or "").strip()
    if text:
        parts.append(text)
    parts.append(
        "Nice effort working through those questions — you're ready to move on."
    )
    return "\n\n".join(parts)


async def evaluate_cluster_teachback_answer(
    session: Session,
    session_id: PydanticObjectId,
    *,
    student_answer: str,
    question: str,
    concepts: list[str],
) -> dict[str, Any]:
    """LLM evaluation with transparent 0–100 score and ideal-answer summary."""
    from app.services.evaluation_engine import clean_context
    from app.services.rag_service import RAGService
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository

    concepts = [str(c).strip() for c in concepts if str(c).strip()]
    reference = await build_cluster_teachback_eval_context(session, session_id, question)
    context_block = clean_context(reference) or ""
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    required_labels = list(coverage.get("coverage_labels") or [])
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    required_count = int(coverage.get("coverage_count") or len(required_labels) or 0)

    if not (student_answer or "").strip():
        return {
            "score": 0,
            "correct": False,
            "feedback": "Please share your explanation in your own words.",
            "missing_points": required_labels or concepts,
            "score_rationale": "There was no answer to evaluate.",
            "ideal_answer": "",
        }

    concepts_str = ", ".join(f'"{c}"' for c in concepts) if concepts else "(cluster)"
    coverage_line = ""
    if required_labels:
        coverage_line = (
            f"\nREQUIRED CHARACTERISTICS ({required_count}): "
            + "; ".join(_display_point(l) for l in required_labels)
        )
    topic_line = ""
    if topic_anchor:
        topic_line = (
            f'\nTOPIC CONTEXT: "{topic_anchor}" is the umbrella topic — grading is on '
            f"the {required_count} characteristics below it, NOT on restating the "
            f"topic title as a separate point."
        )

    prompt = f"""\
You are an expert, empathetic tutor evaluating a student's LONG teachback answer.

TEACHBACK QUESTION:
{question.strip()}

CLUSTER CONCEPTS: {concepts_str}{coverage_line}{topic_line}

STUDENT ANSWER:
{student_answer.strip()}

EVALUATION RULES:
1. Grade MEANING and understanding — not exact wording.
2. Compare ONLY to the authoritative lesson content in the context below.
3. Be fair: paraphrases and informal language count when the idea is right.
4. The topic anchor/title alone does NOT count as covering a characteristic.
5. score_rationale must briefly say WHY you chose that number (1–2 sentences).
6. ideal_answer must restate the correct cluster explanation using ONLY lesson content
   and cover exactly the taught characteristics (not topic title as an extra item).

SCORING GUIDE:
  80–100 : Strong, covers the taught characteristics well.
  50–79  : Partial — some key ideas present, important gaps remain.
  0–49   : Weak — major gaps or misconceptions.

Respond ONLY with valid JSON (no markdown):
{{"score": <int 0-100>, "score_rationale": "<why this score>", "feedback": "<warm 1-2 sentences>", "missing_points": ["<gap>"], "ideal_answer": "<correct summary from lesson>"}}"""

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
            user_intent="EVALUATE",
            current_concept=concepts[0] if concepts else None,
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            rest = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            text = rest.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                raise ValueError("no JSON") from None
            data = json.loads(m.group(0))
        score = max(0, min(100, int(data.get("score", 0))))
        return {
            "score": score,
            "correct": score >= CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD,
            "feedback": str(data.get("feedback") or "").strip(),
            "missing_points": [
                str(p).strip()
                for p in (data.get("missing_points") or [])
                if str(p).strip()
            ],
            "score_rationale": str(data.get("score_rationale") or "").strip(),
            "ideal_answer": str(
                data.get("ideal_answer")
                or data.get("correct_answer_summary")
                or ""
            ).strip(),
        }
    except Exception:
        logger.exception("[CLUSTER_TEACHBACK] LLM evaluation failed — rule fallback")
        from app.services.evaluation_engine import evaluate_answer

        base = await evaluate_answer(concepts or ["cluster"], student_answer, reference)
        score = int(base.get("score", 0) or 0)
        return {
            **base,
            "score": score,
            "score_rationale": str(base.get("feedback") or "").strip(),
            "ideal_answer": "",
        }


async def generate_cluster_socratic_question(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    concepts: list[str],
    missing_points: list[str],
    prior_answer: str,
    turn_index: int,
) -> str:
    """One short Socratic probe grounded in missing taught points."""
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
    taught_block = _teachback_lesson_block(taught_ctx)
    cluster_label = ", ".join(concepts[:6]) if concepts else "this cluster"
    gaps = ", ".join(_display_point(p) for p in missing_points[:4]) or cluster_label

    from app.models.identification.student_profiles import StudentProfile
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.handlers.quiz_handler import _rag_prompt_boundary_kwargs
    from app.services.rag_service import RAGService

    prompt = (
        f"The student is doing cluster teachback for: {cluster_label}.\n"
        f"Their latest answer:\n{prior_answer[:2000]}\n\n"
        f"Gaps to probe: {gaps}\n\n"
        "Write EXACTLY ONE short Socratic follow-up question.\n"
        "Return JSON only: {\"question\":\"...\"}\n"
        "Rules: end with ?; warm tone; do NOT reveal the answer; "
        "focus on one missing taught point; use ONLY lesson content below."
    )
    rag_service = RAGService(
        TopicNoteRepository(),
        VideoSubtitleRepository(),
        TopicQuestionRepository(),
        ctx.topic_repository,
    )
    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    boundary = _rag_prompt_boundary_kwargs(session, topic)
    try:
        raw = await rag_service.generate_prompt(
            question=prompt,
            context=taught_block or gaps,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic.topic_name if topic else None,
            learning_state="teachback",
            user_intent="QUESTION_GENERATION",
            current_concept=cluster_label,
            **boundary,
        )
        data = _parse_json_object(raw or "")
        if data:
            q = str(data.get("question") or "").strip()
            if len(q) >= 12 and "?" in q:
                return q.split("?", 1)[0].strip() + "?"
    except Exception:
        logger.exception("[CLUSTER_TEACHBACK] Socratic question LLM failed turn=%s", turn_index)

    if missing_points:
        focus = _display_point(missing_points[turn_index % len(missing_points)])
        return f"What can you tell me about {focus} in your own words?"
    return "What is one important idea from this cluster that we haven't covered yet?"


async def build_cluster_whiteboard_explanation(
    session: Session,
    session_id: PydanticObjectId,
    *,
    missing_points: list[str] | None = None,
) -> str:
    """Compose explanation text from authoritative cluster lesson content."""
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
    taught_block = _teachback_lesson_block(taught_ctx)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    points = [
        _display_point(p)
        for p in coverage.get("coverage_labels") or coverage.get("coverage_facts") or []
        if _display_point(p)
    ]
    if missing_points:
        focus = [_display_point(p) for p in missing_points if _display_point(p)]
    else:
        focus = points
    if taught_block:
        header = "Let me walk through what we taught on the board:"
        if focus:
            return f"{header}\n\n{taught_block}\n\nPay special attention to: {'; '.join(focus[:6])}."
        return f"{header}\n\n{taught_block}"
    if focus:
        return (
            "Here's what this cluster covered: "
            + "; ".join(focus)
            + ". Each of these is an important characteristic from the lesson."
        )
    return "Let's review the main ideas from this cluster using what we saw on the board."


async def generate_cluster_teachback_simple_ideal_explanation(
    session: Session,
    session_id: PydanticObjectId,
    *,
    question: str,
    concepts: list[str],
    missing_points: list[str] | None = None,
) -> str:
    """
    Plain-language model answer after partial-score Socratic loop — no VTSE.

    Gives the student the perfect teachback answer in warm, easy wording.
    """
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
    taught_block = _teachback_lesson_block(taught_ctx)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    labels = list(coverage.get("coverage_labels") or [])
    facts = list(coverage.get("coverage_facts") or [])
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    cluster_label = ", ".join(concepts[:6]) if concepts else "this cluster"
    gaps = ", ".join(_display_point(p) for p in (missing_points or [])[:4])

    required_lines = []
    for i, label in enumerate(labels):
        detail = facts[i] if i < len(facts) else label
        required_lines.append(f"- {_display_point(label)}: {_display_point(detail)}")
    required_block = "\n".join(required_lines) if required_lines else taught_block

    fallback_parts = [
        "Here's the full answer in simple words:",
    ]
    if topic_anchor and labels:
        fallback_parts.append(
            f"{topic_anchor} means living things that "
            + ", ".join(
                _display_point(l).lower() for l in labels[:3]
            )
            + "."
        )
    elif labels:
        fallback_parts.append(
            "The main ideas are: " + "; ".join(_display_point(l) for l in labels) + "."
        )
    fallback = " ".join(fallback_parts)

    from app.models.identification.student_profiles import StudentProfile
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.rag_service import RAGService

    prompt = (
        f"The student finished two Socratic follow-ups for cluster teachback on: "
        f"{cluster_label}.\n\n"
        f"ORIGINAL TEACHBACK QUESTION:\n{question.strip()}\n\n"
    )
    if gaps:
        prompt += f"GAPS THEY STILL MISSED: {gaps}\n\n"
    if topic_anchor:
        prompt += (
            f'TOPIC CONTEXT: "{topic_anchor}" (umbrella only — not a separate item)\n\n'
        )
    prompt += (
        "Write the PERFECT answer to the teachback question in plain, friendly language.\n"
        "Rules:\n"
        "- 4–7 short sentences; warm tutor tone\n"
        "- Cover EVERY required characteristic below with a simple explanation each\n"
        "- Use everyday words a young student understands\n"
        "- Do NOT ask a new question\n"
        "- Do NOT mention scores or grading\n"
        "- Use ONLY lesson content below\n\n"
        f"REQUIRED CHARACTERISTICS:\n{required_block}\n"
    )
    if taught_block:
        prompt += f"\nLESSON CONTENT:\n{taught_block}\n"

    rag_service = RAGService(
        TopicNoteRepository(),
        VideoSubtitleRepository(),
        TopicQuestionRepository(),
        TopicRepository(),
    )
    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    try:
        raw = await rag_service.generate_prompt(
            question=prompt,
            context=taught_block or required_block or cluster_label,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=None,
            learning_state="teachback",
            user_intent="EXPLAIN",
            current_concept=cluster_label,
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            rest = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            text = rest.rsplit("```", 1)[0].strip()
        if len(text.split()) >= 12:
            return text
    except Exception:
        logger.exception("[CLUSTER_TEACHBACK] simple ideal explanation LLM failed")

    return fallback


async def generate_cluster_teachback_question(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    concepts: list[str],
) -> str:
    """Generate one long, grounded teachback question for the cluster."""
    taught_ctx = await resolve_cluster_teachback_taught_context(session, session_id)
    taught_block = _teachback_lesson_block(taught_ctx)
    coverage = teachback_coverage_from_ctx(taught_ctx)
    coverage_labels = list(coverage.get("coverage_labels") or [])
    coverage_facts = list(coverage.get("coverage_facts") or [])
    topic_anchor = str(coverage.get("topic_anchor") or "").strip()
    cluster_label = ", ".join(concepts[:6]) if concepts else "this cluster"

    fallback = fallback_cluster_teachback_question(
        concepts,
        coverage_labels,
        topic_anchor=topic_anchor,
        coverage_facts=coverage_facts,
    )

    if not taught_block and not coverage_labels:
        return fallback

    from app.models.identification.student_profiles import StudentProfile
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.handlers.quiz_handler import _rag_prompt_boundary_kwargs
    from app.services.rag_service import RAGService

    coverage_block = _teachback_coverage_prompt_block(coverage)

    prompt = (
        f'Create ONE comprehensive teachback question for cluster: "{cluster_label}".\n'
        "The student will answer in their own words in a long paragraph.\n"
        "Return JSON only:\n"
        '{"question":"..."}\n'
        "Rules:\n"
        "- One natural, student-friendly question (2-4 sentences).\n"
        "- Ask them to describe/explain ALL characteristics listed below.\n"
        "- Ask for a brief explanation of EACH characteristic (not just naming them).\n"
        "- Use ONLY the lesson content below — do not invent facts or extra topics.\n"
        "- The topic anchor is context only — do NOT ask the student to explain the "
        "topic title as if it were a separate characteristic.\n"
        "- Do NOT use vague prompts like 'how do these ideas connect' without naming "
        "the specific characteristics.\n"
    )
    if coverage_block:
        prompt += f"\n{coverage_block}\n"
    if taught_block:
        prompt += f"\nLESSON CONTENT:\n{taught_block}\n"

    topic_question_repository = TopicQuestionRepository()
    topic_note_repository = TopicNoteRepository()
    video_subtitle_repository = VideoSubtitleRepository()
    rag_service = RAGService(
        topic_note_repository,
        video_subtitle_repository,
        topic_question_repository,
        ctx.topic_repository,
    )
    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    boundary = _rag_prompt_boundary_kwargs(session, topic)

    for attempt in range(3):
        try:
            raw = await rag_service.generate_prompt(
                question=prompt,
                context=taught_block or coverage_block or cluster_label,
                student_profile=student_profile.model_dump() if student_profile else None,
                topic_name=topic.topic_name if topic else None,
                learning_state="teachback",
                user_intent="QUESTION_GENERATION",
                current_concept=cluster_label,
                **boundary,
            )
            data = _parse_json_object(raw or "")
            if not data:
                continue
            question = str(data.get("question") or "").strip()
            if validate_cluster_teachback_question(
                question, taught_ctx, coverage_labels
            ):
                return question if question.endswith("?") else f"{question.rstrip('.')}?"
        except Exception:  # noqa: BLE001
            logger.exception(
                "[CLUSTER_TEACHBACK] LLM question failed cluster=%s attempt=%s",
                cluster_label,
                attempt,
            )

    logger.warning(
        "[CLUSTER_TEACHBACK] using fallback question cluster=%s", cluster_label
    )
    return fallback
