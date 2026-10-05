"""
Explanation handler — standalone async functions extracted from SessionService.

All logic is IDENTICAL to the original private methods in session_service.py.
`self.*` references have been replaced with the HandlerContext `ctx` parameter
or with local pure-function helpers defined below.  SessionService is never
imported here.

`generate_tutor_rag_reply` does NOT need HandlerContext because it already
receives all dependencies as explicit parameters (rag_service, context,
student_profile, event_repository).

Public API (called from session_service.py):

Pure functions (no async, no I/O):
    build_explanation_response(answer, intent, learning_state, *, optional_note) -> str
    build_feedback_response(feedback, correct, *, attempts, sus_score) -> str
    teacher_buttons(items) -> list[dict]

Async handlers:
    generate_tutor_rag_reply(session, session_id, student_id, question,
                             topic_id, intent, state_at_entry, topic_for_prompt,
                             rag_service, context, student_profile,
                             event_repository) -> str
    teacher_explain_turn(ctx, session, session_id, student_id, topic,
                         rag_question, *, intent, state_at_entry,
                         next_flow_state, next_learning_state) -> str | dict | None
    teacher_advance_skip(ctx, session, session_id, student_id, topic) -> dict
    should_run_micro_teaching(session) -> bool
    teacher_micro_teaching_opening(...) -> str
    teacher_micro_teaching_process_reply(...) -> str
"""

from __future__ import annotations

import json
import random
import re
import time
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from beanie.odm.fields import PydanticObjectId

from app.enums.learning_enums import SessionEventType
from app.core.config import Settings
from app.models.curriculum.topics import Topic
from app.models.intelligence.ai_generation_logs import AIGenerationLog
from app.models.learning.mastery_records import (
    mastery_record_filter,
    normalize_concept,
)
from app.repositories.mastery_repository import MasteryRepository
from app.models.teacher_topic import TeacherTopic
from app.repositories.event_repository import EventRepository
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.handlers.cluster_utils import (
    flat_index_is_first_in_its_cluster,
    resolve_clusters,
)
from app.services.misconception_service import handle_misconception
from app.services.rag_service import RAGService
from app.services.handlers.text_only_reply import (
    PLAIN_TEXT_REPLY_SUFFIX,
    coerce_plain_text_reply,
)
from app.core.constants import (
    MICRO_TEACH_MAX_LOOPS,
    MICRO_TEACH_MIN_WORDS_FOR_COMPLETION,
    MICRO_TEACH_PASS_SCORE,
    MICRO_TEACH_STEP_READY_QUIZ,
)
from app.services.evaluation_engine import evaluate_answer as _engine_evaluate_answer
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator

if TYPE_CHECKING:
    from app.models.identification.student_profiles import StudentProfile
    from app.models.learning.sessions import Session
    from app.repositories.topic_repository import TopicRepository
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)


def _parse_structured_output(text: str):
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            data = json.loads(candidate)
            if isinstance(data, dict) and "explanation" in data:
                return data
    except Exception:
        pass
    return None


def _extract_structured_answer(answer: str):
    parsed = _parse_structured_output(answer or "")
    if parsed:
        explanation = str(parsed.get("explanation") or "").strip()
        visual = parsed.get("visual") if isinstance(parsed.get("visual"), dict) else None
        return explanation, visual
    return (answer or "").strip(), None


def _coerce_rag_answer(answer: str) -> str:
    """Plain teaching text only — legacy JSON/visual replies are stripped."""
    extracted, _ = _extract_structured_answer(answer)
    return coerce_plain_text_reply(extracted)


# ─────────────────────────────────────────────────────────────────────────────
# Private pure-function helpers (mirrors of SessionService static methods)
# ─────────────────────────────────────────────────────────────────────────────


def _is_teacher_progression(session: Session) -> bool:
    return (getattr(session, "total_concepts", 0) or 0) > 0


def _session_concept_sequence(
    session: Session, topic: Topic | TeacherTopic | None
) -> list[str]:
    kc = list(getattr(session, "key_concepts", None) or [])
    if kc:
        return [str(c).strip() for c in kc if c is not None and str(c).strip()]
    if topic is None:
        return []
    return [
        str(c).strip()
        for c in (topic.key_concepts or [])
        if c is not None and str(c).strip()
    ]


def _get_current_concept(
    session: Session, topic: Topic | TeacherTopic | None
) -> str | None:
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return None
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if idx < 0 or idx >= len(concepts):
        return None
    return concepts[idx]


def _get_next_concept(
    session: Session, topic: Topic | TeacherTopic | None
) -> str | None:
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return None
    idx = int(getattr(session, "current_concept_index", 0) or 0) + 1
    if idx < 0 or idx >= len(concepts):
        return None
    return concepts[idx]


def _rag_prompt_boundary_kwargs(
    session: Session, topic: Topic | TeacherTopic | None
) -> dict[str, Any]:
    if not _is_teacher_progression(session):
        return {}
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return {}
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if idx < 0:
        idx = 0
    if idx > len(concepts):
        idx = len(concepts)
    learned_list = concepts[:idx]
    next_concept = concepts[idx + 1] if idx + 1 < len(concepts) else None
    return {
        "enforce_knowledge_boundary": True,
        "learned_concepts_list": learned_list,
        "next_concept": next_concept,
    }


def _teacher_debug_flow(session: Session, topic: Topic | TeacherTopic | None) -> None:
    next_c = _get_next_concept(session, topic)
    print(
        "FLOW:",
        getattr(session, "flow_state", None),
        "CURRENT:",
        getattr(session, "current_concept", None),
        "NEXT:",
        next_c,
    )


def _remember_learned_concept(session: Session, concept: str | None) -> None:
    nc = normalize_concept(concept)
    if nc is None:
        return
    nc_norm = str(nc).strip().lower()
    if not nc_norm:
        return
    learned = list(getattr(session, "learned_concepts", None) or [])
    learned_norm_set = {
        str(x).strip().lower() for x in learned if x is not None and str(x).strip()
    }
    if nc_norm in learned_norm_set:
        return
    session.learned_concepts = learned + [nc_norm]


async def _get_topic_or_teacher_topic_impl(
    topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic | TeacherTopic | None:
    t = await topic_repository.get_by_id(topic_id)
    if t is not None:
        return t
    return await TeacherTopic.get(topic_id)


# ─────────────────────────────────────────────────────────────────────────────
# Public pure functions (exported to session_service.py and other callers)
# ─────────────────────────────────────────────────────────────────────────────


def build_explanation_response(
    answer: str,
    intent: str,
    learning_state: str,
    *,
    optional_note: str | None = None,
) -> str:
    """
    Human-style explanation: acknowledgement + optional note + body.
    No quiz question embedded. Closing check only if already checking_understanding.
    """
    answer = (answer or "").strip()
    note = (optional_note or "").strip()
    if intent == "UNKNOWN":
        ack = "No worries, let's break it down simply"
    elif intent == "EXPLAIN":
        ack = random.choice(
            [
                "Good question 👍",
                "Got it — let me explain clearly",
            ]
        )
    else:
        ack = random.choice(
            [
                "Good question 👍",
                "Got it — let me explain clearly",
            ]
        )
    parts: list[str] = [ack]
    if note:
        parts.append(note)
    if answer:
        parts.append(answer)
    body = "\n\n".join(parts)
    if learning_state == "checking_understanding":
        body = (
            f"{body}\n\n"
            "Does that make sense? If not, say so and we'll keep working on it together."
        )
    return body.strip()


def build_feedback_response(
    feedback: str,
    correct: bool,
    *,
    attempts: int = 0,
    sus_score: float = 50.0,
) -> str:
    """
    Build a human-like, adaptive feedback lead line.

    Correct responses vary in tone based on the student's SUS score:
      - High SUS (>70): concise, matter-of-fact praise
      - Normal SUS (40–70): standard warm encouragement
      - Low SUS (<40): extra warm and supportive

    Incorrect responses escalate in empathy with the attempt count:
      - Attempt 1: light, optimistic nudge
      - Attempt 2: constructive, step-by-step invitation
      - Attempt 3+: patient, supportive re-explanation cue
    """
    if correct:
        if sus_score > 70:
            options = [
                "That's accurate.",
                "Correct — your reasoning lines up.",
                "Yes, that's the key idea.",
                "That matches the concept.",
            ]
        elif sus_score < 40:
            options = [
                "That's correct. Keep building from this step.",
                "Yes — that idea is right. Let's continue steadily.",
                "Correct. You're moving in the right direction.",
                "That works. We'll build the next piece from here.",
            ]
        else:
            options = [
                "That's correct.",
                "Yes, that fits.",
                "Right — that's the idea.",
                "That's on track.",
                "Right — that lines up with the thread of your reasoning.",
                "That fits what you were saying about the idea.",
            ]
        lead = random.choice(options)
    else:
        attempt = max(0, int(attempts or 0))
        if attempt <= 1:
            options = [
                "You're close — let's refine your understanding.",
                "Not quite, but you're on the right track — let's look at this together.",
                "Almost there — let's work through it a bit more.",
            ]
        elif attempt == 2:
            options = [
                "Good effort — let's break this down step by step.",
                "Nice try — let me walk through this more carefully with you.",
                "You're putting in the effort — let's go through each part slowly.",
            ]
        else:
            options = [
                "This one is tricky — let me explain it as clearly as I can.",
                "Don't worry — this is a challenging concept. Let's go through it together.",
                "No problem at all — let me take a different angle on this.",
            ]
        lead = random.choice(options)

    fb = (feedback or "").strip()
    if fb:
        return f"{lead}\n\n{fb}".strip()
    return lead


def teacher_buttons(items: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": a, "label": b} for a, b in items]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: Six-step teaching helper (pure function — no I/O, no LLM calls)
# ─────────────────────────────────────────────────────────────────────────────


def build_six_step_explanation(
    concept: Optional[str],
    student_profile: Any,
    context: str,
) -> dict:
    """
    Return a structured 4-step teaching response for a single concept.

    Steps:
      1. Familiarity check   — invite the student to reflect on prior exposure.
      2. Real-life hook      — connect the concept to the student's interests.
      3. Short explanation   — up to 3 lines extracted from curriculum context.
      4. Guided question     — prompt the student to explain it in their own words.

    This is a pure function: no network calls, no database access, no LLM.
    The response dict is compatible with existing callers (has 'type' + 'message').
    """
    concept_label = (concept or "this concept").strip()

    # Step 1 — familiarity check
    step1 = (
        f"Before we start — have you come across **{concept_label}** before? "
        "Take a moment to think about whether it sounds familiar or completely new to you."
    )

    # Step 2 — real-life hook (personalised when student_profile has interests)
    raw_interests: list[str] = []
    if student_profile is not None:
        raw = getattr(student_profile, "interests", None) or []
        raw_interests = [str(i).strip() for i in raw if i is not None and str(i).strip()]
    hook_detail = f" — particularly in the context of {raw_interests[0]}" if raw_interests else ""
    step2 = (
        f"Here's where **{concept_label}** shows up in real life{hook_detail}: "
        "think about everyday situations where this idea plays a role, "
        "even if you've never called it by name."
    )

    # Step 3 — short explanation from curriculum notes (max ~3 content lines / 600 chars)
    content_lines = [ln.strip() for ln in context.strip().splitlines() if ln.strip()]
    excerpt = " ".join(content_lines[:3])
    if len(excerpt) > 600:
        excerpt = excerpt[:597] + "…"
    if not excerpt:
        excerpt = f"Let's explore {concept_label} together using what we know so far."
    step3 = f"Here's the core idea:\n\n{excerpt}"

    # Step 4 — guided question
    step4 = (
        f"Now it's your turn: how would you explain **{concept_label}** "
        "to a friend who's never heard of it before? "
        "Use your own words — there's no wrong answer."
    )

    steps = [step1, step2, step3, step4]
    message = "\n\n---\n\n".join(steps)
    return {
        "type": "six_step_explanation",
        "message": message,
        "concept": concept_label,
        "steps": steps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5: Zone pedagogy overlay (pure function — no I/O, no LLM calls)
# ─────────────────────────────────────────────────────────────────────────────

# Per-zone pedagogical notes appended to the end of any explanation response.
# They are intentionally short so they complement rather than compete with the
# LLM content or the six_step template.
_ZONE_PEDAGOGY_NOTES: dict[int, str] = {
    # Zone 1 — foundational / structured: invite questions, offer scaffolding.
    1: (
        "\n\n> **Tip:** Take your time with this. If anything feels unclear "
        "or you'd like me to go deeper on any part, just ask!"
    ),
    # Zone 2 — Socratic / application: prompt "why" and "how" thinking.
    2: (
        "\n\n> **Think deeper:** Now that you've seen the idea — *why* does it "
        "work this way? Can you think of a real situation where you'd apply it?"
    ),
    # Zone 3 — minimal framework: push independent problem-solving, offer hints.
    3: (
        "\n\n> **Your move:** Try working through this yourself before asking "
        "for the full answer. I'll give you a hint if you get stuck."
    ),
    # Zone 4 — curiosity / mastery: open-ended critical-thinking challenge.
    4: (
        "\n\n> **Challenge:** Can you think of a scenario where this idea breaks "
        "down, or connects to something unexpected? Push your thinking further."
    ),
}


def apply_zone_pedagogy(zone: int, base_response: str | dict) -> str | dict:
    """
    Layer zone-specific pedagogical guidance on top of an explanation response.

    Zones map to teaching stances:
      Zone 1 → structured, supportive — invites questions and hints.
      Zone 2 → Socratic / application — prompts "why" and "how" reflection.
      Zone 3 → independent solving — encourages trying first, hints on request.
      Zone 4 → critical thinking — open-ended challenge, cross-domain thinking.

    Accepts and returns either a str (standard RAG output) or a dict
    (six_step / any structured response), so callers need no type checks.
    Zones outside 1–4 are silently ignored and the response is returned as-is.
    """
    # Zones 1–2 share VTSE — use Zone 1 overlay for both.
    effective_zone = 1 if zone == 2 else zone
    note = _ZONE_PEDAGOGY_NOTES.get(effective_zone, "")
    if not note:
        return base_response

    if isinstance(base_response, dict):
        updated = dict(base_response)
        updated["message"] = updated.get("message", "") + note
        updated["pedagogy_note"] = note.strip()
        return updated

    return str(base_response) + note


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6: Spaced retrieval helpers (pure functions — no I/O, no LLM calls)
# ─────────────────────────────────────────────────────────────────────────────


def get_due_concepts(
    mastery_records: list,
    now: datetime,
    *,
    exclude_concepts: Optional[set[str]] = None,
) -> list[str]:
    """
    Return concept names that are due for spaced retrieval.

    Only concepts that have been reviewed at least once are considered —
    never-reviewed concepts (``last_reviewed_at`` is None) are skipped because
    there is nothing in long-term memory to retrieve yet.

    Args:
        mastery_records:  Iterable of MasteryRecord-like objects.
        now:              Current UTC timestamp.
        exclude_concepts: Names to skip — typically the current concept and
                          any concept already reviewed this session.

    Returns:
        List of concept names in the order they appear in mastery_records.
        At most one is used by the caller (max-1-per-turn rule).
    """
    _exclude = exclude_concepts or set()
    due: list[str] = []
    for rec in mastery_records:
        concept = getattr(rec, "concept", None)
        if not concept or concept in _exclude:
            continue
        last_reviewed = getattr(rec, "last_reviewed_at", None)
        if last_reviewed is None:
            # Never reviewed → nothing to retrieve yet.
            continue
        interval = float(getattr(rec, "review_interval_days", 1.0) or 1.0)
        elapsed_days = (now - last_reviewed).total_seconds() / 86_400.0
        if elapsed_days >= interval:
            due.append(concept)
    return due


def _apply_retrieval_prefix(
    prefix: Optional[str],
    response: str | dict,
) -> str | dict:
    """
    Prepend a spaced-retrieval prompt to an explanation response.

    Handles both str (standard RAG) and dict (six_step / structured) responses
    so callers need no type guards.  When ``prefix`` is None or empty the
    response is returned unchanged.
    """
    if not prefix:
        return response
    separator = "\n\n---\n\n"
    if isinstance(response, dict):
        updated = dict(response)
        updated["message"] = prefix + separator + updated.get("message", "")
        updated["retrieval_prompt"] = prefix.strip()
        return updated
    return prefix + separator + str(response)


# ─────────────────────────────────────────────────────────────────────────────
# Public async handler functions
# ─────────────────────────────────────────────────────────────────────────────


async def generate_tutor_rag_reply(
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    question: str,
    topic_id: PydanticObjectId,
    intent: str,
    state_at_entry: str,
    topic_for_prompt: Topic | TeacherTopic | None,
    rag_service: RAGService,
    context: str,
    student_profile: StudentProfile | None,
    event_repository: EventRepository,
    *,
    persist_session_qa: bool = True,
) -> str:
    """
    Call the RAG service to generate a tutor reply, persist AI log and answer
    event, and update session.last_question / session.last_answer.

    Internal grading/feedback prompts (concept check praise, etc.) must pass
    persist_session_qa=False so long LLM prompts are not stored as last_question.

    Does NOT need HandlerContext — all dependencies are passed as parameters.
    """
    if not context or len(context.strip()) < 50:
        return "I don't have enough information on this topic yet."
    start_time = time.time()
    prior_last_answer = getattr(session, "last_answer", None)
    is_followup_turn = bool(prior_last_answer) and intent in (
        "EXPLAIN",
        "UNKNOWN",
        "CONFIRM",
    )
    mastery_row = await MasteryRepository().get_one(
        mastery_record_filter(
            session.organization_id,
            student_id,
            topic_id,
            normalize_concept(getattr(session, "current_concept", None)),
        )
    )
    mastery_for_prompt = (
        float(mastery_row.mastery_score) if mastery_row is not None else None
    )
    ev_for_prompt = EventRepository()
    ev_list = await ev_for_prompt.get_session_events(session_id, limit=80)
    last_ans_correct_for_prompt = None
    for e in reversed(ev_list):
        if e.event_type == SessionEventType.ANSWER:
            last_ans_correct_for_prompt = getattr(e, "is_correct", None)
            break
    _remember_learned_concept(session, getattr(session, "current_concept", None))
    boundary = _rag_prompt_boundary_kwargs(session, topic_for_prompt)
    answer = await rag_service.generate_prompt(
        question=f"{question}{PLAIN_TEXT_REPLY_SUFFIX}",
        context=context,
        student_profile=student_profile.model_dump() if student_profile else None,
        topic_name=topic_for_prompt.topic_name if topic_for_prompt else None,
        learning_state=state_at_entry,
        user_intent=intent,
        last_answer=prior_last_answer if is_followup_turn else None,
        is_followup=is_followup_turn,
        current_concept=getattr(session, "current_concept", None),
        mastery_score=mastery_for_prompt,
        last_answer_correct=last_ans_correct_for_prompt,
        **boundary,
    )
    answer = _coerce_rag_answer(answer or "")
    if persist_session_qa:
        session.last_question = (question or "")[:5000] or None
        session.last_answer = (answer or "")[:12000] or None
        await session.save()
    response_time_ms = int((time.time() - start_time) * 1000)
    await AIGenerationLog(
        organization_id=session.organization_id,
        student_id=student_id,
        topic_id=topic_id,
        session_id=session_id,
        model_used=Settings.DEEPSEEK_MODEL,
        task_type="qa",
        tokens_used=0,
        estimated_cost=0,
        response_time_ms=response_time_ms,
    ).insert()
    if persist_session_qa:
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.ANSWER,
                "content": (answer[:4000] if len(answer) > 4000 else answer),
                "timestamp": datetime.utcnow(),
            }
        )
    return answer


def _micro_ensure_engagement_closer(text: str) -> str:
    """
    Micro-teaching messages must never dead-end: require a question or a thinking prompt.
    """
    t = (text or "").strip()
    if not t:
        return "What is one thing you already associate with this idea?"
    lower = t.lower()
    if "?" in t:
        return t
    if any(
        phrase in lower
        for phrase in (
            "think about",
            "consider ",
            "take a moment",
            "what if",
            "how would you",
            "in your own words",
            "pause and",
            "try to picture",
            "reflect on",
        )
    ):
        return t
    return f"{t}\n\nWhat part of that still feels fuzzy — can you name it in one phrase?"


def _micro_strip_questions_for_handoff(text: str) -> str:
    """
    For micro-loop close handoff, remove model-generated question lines so
    the handoff stays statement-only before the explicit Q&A invitation.
    """
    t = (text or "").strip()
    if not t:
        return t
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    kept = [ln for ln in lines if "?" not in ln]
    if not kept:
        return "Nice work — you've connected the core idea."
    return "\n".join(kept).strip()


def _micro_question_only(text: str) -> str:
    """
    Return exactly one question line (first sentence containing '?').
    If none found, return a safe Socratic fallback question.
    """
    fallback = "What part of your answer do you want to rethink?"
    t = (text or "").strip()
    if not t:
        return fallback
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    for ln in lines:
        if "?" in ln:
            q = ln.split("?", 1)[0].strip()
            if q:
                out = f"{q}?"
                return out if out.strip() else fallback
    q = t.split("?", 1)[0].strip()
    if q:
        out = f"{q}?"
        return out if out.strip() else fallback
    return fallback


def _enforce_explain_then_one_question(
    text: str, *, fallback_expl: str, max_expl_sentences: int = 2
) -> str:
    """
    Enforce: short explanation (1-2 sentences) followed by exactly one question.
    Used for non-probe explanation paths.
    """
    t = (text or "").strip()
    if not t:
        return f"{fallback_expl.strip()} What do you notice first?"
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    questions = [p for p in parts if p.endswith("?") or "?" in p]
    q = ""
    if questions:
        raw_q = questions[0]
        q = raw_q.split("?", 1)[0].strip()
    if not q:
        # fallback to first sentence as a transformed question
        base = parts[0].rstrip(".! ").strip() if parts else "this idea"
        q = f"What do you notice about {base.lower()}".strip()
    question = f"{q}?"

    expl_parts = [p for p in parts if p not in questions]
    expl = " ".join(expl_parts[:2]).strip()
    if not expl:
        expl = fallback_expl.strip()
    # Keep explanation concise with adaptive cap (1-4 short sentences).
    sent_cap = max(1, min(4, int(max_expl_sentences or 2)))
    expl_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", expl) if s.strip()]
    expl = " ".join(expl_sents[:sent_cap]).strip()
    if not expl.endswith((".", "!", "?")):
        expl = f"{expl}."
    return f"{expl} {question}".strip()


def _micro_adaptive_expl_sentence_cap(
    *, mc_action: str, score: int, missing_points: list[str]
) -> int:
    """
    Adaptive explanation length for Zone 1:
    - close: 1-2 sentences
    - partial: 2-3 sentences
    - wrong/confused: 3-4 sentences
    """
    m_count = len([m for m in (missing_points or []) if str(m).strip()])
    if mc_action == "confirm":
        return 2
    if score >= 75 and m_count <= 1:
        return 2
    if score >= 45 or m_count <= 2:
        return 3
    return 4


# Zone 1 micro-teaching: explain one meaningful idea, then ask one question.
_MICRO_CALM_BREVITY = (
    "VOICE — CALM GUIDE (mandatory):\n"
    "- Keep praise sparse and varied; do not start every reply with 'Nice', 'Good', or 'Great'.\n"
    "- Respond like a natural human tutor: warm but not over-praising, conversational (not scripted), and slightly varied in sentence openings.\n"
    "- Occasionally reference the student's answer directly (for example: 'You mentioned...') when useful.\n"
    "- Avoid textbook-style definitions unless necessary.\n"
    "- Teach ONE small meaningful idea clearly (usually 1–3 sentences).\n"
    "- Focus on idea size, not sentence count.\n"
    "- Frequently connect to prior steps, but vary wording naturally "
    "(e.g., 'Let’s tie this back to earlier...', 'If we put these together...', "
    "'Building on that idea...', 'Seen from the previous step...').\n"
    "- Avoid repeating the same transition phrases; use varied natural language such as: "
    "'Think about this...', 'Notice something here...', 'You mentioned...', "
    "'Here's another way to see it...', 'Consider this...', 'Let's connect this idea...'.\n"
    "- Do not reuse the same transition opener in consecutive turns.\n"
    "- Then ask exactly ONE question (no multi-question stacking).\n"
    "- Adjust explanation length based on student understanding:\n"
    "  * small correction -> short,\n"
    "  * moderate confusion -> medium,\n"
    "  * clear misunderstanding -> slightly longer explanation (max 4 sentences).\n"
    "- If the student has already demonstrated the same idea correctly, do not ask another question on that exact same point; "
    "instead ask about a different aspect of the concept or move toward concept closure.\n"
    "- If the student already demonstrated correct understanding of the same idea in the previous turn, "
    "do not repeat a similar check question or re-test that exact point.\n"
    "- If confidence is high, reduce probing intensity and shift toward deeper connection or closure.\n"
    "- Avoid micro-repetition across turns: do not reuse the same concept phrasing, sentence structure, or question pattern.\n"
    "- Do not repeat the exact previous question.\n"
    "- If confusion is visible, simplify wording and ask an easier follow-up.\n"
    "- NEVER use restart phrases: 'let's review', 'let's start from', 'main idea again', "
    "'let's go back to the beginning', or 'let me re-explain from the top'.\n"
    "- When re-clarifying, use fresh, context-specific wording instead of fixed templates.\n\n"
    "CONCEPT BOUNDARY (strict):\n"
    "- Stay inside the CURRENT concept only.\n"
    "- Do NOT ask about next concepts, unseen definitions, or advanced terms not yet taught.\n"
    "- Ask from the immediately previous explanation line, not from future content.\n\n"
)


# Semantic teaching stages: each round covers a different aspect of the concept.
# Stage is derived from prev_rounds (= current_step_in_concept) — no new session field needed.
_STAGE_INSTRUCTIONS: dict[int, str] = {
    0: (
        "SEMANTIC STAGE 0 — INTRODUCE THE IDEA: "
        "State in plain language what this concept IS. Give the simplest definition or analogy. "
        "Do not explain inputs, mechanism, or outcome yet — just the core idea."
    ),
    1: (
        "SEMANTIC STAGE 1 — INPUTS / COMPONENTS: "
        "Focus on what this concept REQUIRES or consists of. "
        "Name the key ingredients, conditions, or parts that make it work."
    ),
    2: (
        "SEMANTIC STAGE 2 — PROCESS / MECHANISM: "
        "Focus on HOW this concept works. Walk through the sequence of steps or mechanism. "
        "Connect the inputs from the previous stage to what happens next."
    ),
    3: (
        "SEMANTIC STAGE 3 — RESULT / OUTCOME: "
        "Focus on WHAT HAPPENS as a result. What does this concept produce, enable, or achieve? "
        "Tie back to the process to show the complete picture."
    ),
}


def _micro_read_missing_points(eval_result: dict) -> list[str]:
    """Normalize evaluator ``missing_points`` to a list of non-empty strings."""
    raw = eval_result.get("missing_points") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for m in raw:
        s = str(m).strip()
        if s:
            out.append(s)
    return out


def _micro_has_reasoning_or_connection(student_text: str) -> bool:
    """True when the answer reads like reasoning, not only keyword listing."""
    t = (student_text or "").strip()
    if not t:
        return False
    lower = t.lower()
    markers = (
        "because",
        "so ",
        "therefore",
        "means ",
        "when ",
        "if ",
        "how ",
        "why ",
        "which ",
        "depends",
        "connect",
        "together",
        "overall",
        "leads",
        "results",
        "combines",
        "since ",
        "although",
        "compared",
    )
    if any(m in lower for m in markers):
        return True
    if t.count(",") >= 1 and len(t.split()) >= 8:
        return True
    if len(t.split()) >= 22:
        return True
    return False


def _micro_is_shallow_keyword_answer(student_text: str, eval_result: dict) -> bool:
    """
    High-score but thin answers (keywords without explanation) should not complete
    the micro-loop.
    """
    score = int(eval_result.get("score", 0) or 0)
    text = (student_text or "").strip()
    words = text.split()
    nw = len(words)
    if score < 62:
        return False
    if nw <= 5 and score >= 66:
        return True
    if nw <= 12 and score >= 70 and not _micro_has_reasoning_or_connection(text):
        return True
    if nw <= 10 and score >= 68 and text.count(",") >= max(0, nw - 3):
        return True
    return False


def _micro_meets_concept_completion(eval_result: dict, student_text: str) -> bool:
    """
    Quiz handoff only when core ideas are covered (no missing_points), score is
    adequate, the answer is not shallow-keyword, and the student shows reasoning
    or connection—not score or word-count alone.
    """
    if _micro_is_shallow_keyword_answer(student_text, eval_result):
        return False
    missing = _micro_read_missing_points(eval_result)
    if missing:
        return False
    score = int(eval_result.get("score", 0) or 0)
    if score < MICRO_TEACH_PASS_SCORE:
        return False
    words = len((student_text or "").strip().split())
    if words < MICRO_TEACH_MIN_WORDS_FOR_COMPLETION:
        return False
    return _micro_has_reasoning_or_connection(student_text)


def _extract_core_teaching_point(answer_text: str) -> str:
    """
    Normalized fingerprint of the model's last reply (first sentence, trimmed).
    Used only for ``explained_points`` repetition guarding — not for ``taught_points``.
    """
    if not answer_text:
        return ""
    first_sentence = re.split(r"[.!?\n]", answer_text.strip())[0].strip()
    key = re.sub(r"[*_#`]", "", first_sentence).lower().strip()
    return key[:80]


# Taught points derived from concept content, not generated text
_INSTRUCT_TAUGHT_DENY: frozenset[str] = frozenset(
    {
        "explore",
        "refine",
        "connect",
        "think",
        "understanding",
        "understand",
        "discuss",
        "example",
        "important",
        "remember",
        "summary",
        "question",
        "answer",
        "please",
        "could",
        "would",
        "should",
        "might",
        "maybe",
        "learn",
        "learning",
        "lesson",
        "review",
        "practice",
        "try",
        "note",
        "notes",
    }
)
_GENERIC_TAUGHT_SKIP: frozenset[str] = frozenset(
    {
        "thing",
        "things",
        "idea",
        "ideas",
        "part",
        "parts",
        "process",
        "processes",
        "student",
        "teacher",
        "topic",
        "chapter",
        "section",
    }
)

# (substring in normalized corpus, canonical token) — longer phrases first via sort.
_TAUGHT_PHRASE_TO_TOKEN: tuple[tuple[str, str], ...] = (
    ("photosynthesis", "photosynthesis"),
    ("reproduction", "reproduction"),
    ("reproducing", "reproduction"),
    ("reproduce", "reproduction"),
    ("respiration", "respiration"),
    ("respiratory", "respiration"),
    ("breathing", "respiration"),
    ("breathe", "respiration"),
    ("breathes", "respiration"),
    ("breath", "respiration"),
    ("growth", "growth"),
    ("growing", "growth"),
    ("grew", "growth"),
    ("grow", "growth"),
    ("grows", "growth"),
    ("nutrition", "nutrition"),
    ("nutrients", "nutrition"),
    ("nutrient", "nutrition"),
    ("movement", "movement"),
    ("moving", "movement"),
    ("excretion", "excretion"),
    ("sensitivity", "sensitivity"),
    ("stimulus", "sensitivity"),
    ("energy", "energy"),
    ("sunlight", "energy"),
    ("food", "nutrition"),
    ("carbon dioxide", "carbon_dioxide"),
    ("co2", "carbon_dioxide"),
    ("oxygen", "oxygen"),
    ("water", "water"),
    ("cell", "cell"),
    ("cells", "cell"),
    ("organism", "organism"),
    ("organisms", "organism"),
)


def _normalize_taught_corpus(text: str) -> str:
    t = str(text or "").strip().lower()
    t = re.sub(r"[*_#`]", " ", t)
    t = re.sub(r"[^a-z0-9\s-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _taught_points_from_corpus_text(corpus: str, *, concept_title: str) -> list[str]:
    """
    Derive 0–7 canonical taught tokens from curriculum text (concept + notes).
    No LLM output — phrase lexicon + light noun fallback from the concept title only.
    """
    low = _normalize_taught_corpus(corpus)
    if not low and not (concept_title or "").strip():
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for phrase, token in sorted(_TAUGHT_PHRASE_TO_TOKEN, key=lambda x: -len(x[0])):
        if phrase in low and token not in seen:
            if token in _INSTRUCT_TAUGHT_DENY or token in _GENERIC_TAUGHT_SKIP:
                continue
            ordered.append(token)
            seen.add(token)
            if len(ordered) >= 7:
                return ordered
    # Fallback: long alphabetic words from the concept title only (curriculum label).
    title = _normalize_taught_corpus(concept_title)
    for w in re.findall(r"[a-z]{5,}", title):
        if w in _INSTRUCT_TAUGHT_DENY or w in _GENERIC_TAUGHT_SKIP:
            continue
        if w in seen:
            continue
        ordered.append(w[:24])
        seen.add(w)
        if len(ordered) >= 7:
            break
    return ordered[:7]


def _session_key_concepts_for_clusters(
    session: Session, topic: Topic | TeacherTopic | None
) -> list[str]:
    kc = list(getattr(session, "key_concepts", None) or [])
    if not kc and topic is not None:
        kc = [
            str(c).strip()
            for c in (getattr(topic, "key_concepts", None) or [])
            if c is not None and str(c).strip()
        ]
    return kc


def _dedupe_ordered_taught_points(items: list[str], *, cap: int) -> list[str]:
    """Lowercase, dedupe, preserve order, cap length."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        t = str(x).strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= cap:
            break
    return out


def _derive_taught_points_from_micro_context(
    concept_title: str, curriculum_context: str
) -> list[str]:
    """
    Taught points derived from concept content, not generated text.

    ``curriculum_context`` is the same note-backed RAG context used for micro-teaching
    (from ``_micro_build_rag_context`` / ``build_context``), so we do not parse tutor LLM output.
    """
    cc = (concept_title or "").strip()
    corpus = f"{cc}\n{(curriculum_context or '').strip()}"
    return _taught_points_from_corpus_text(corpus, concept_title=cc)


def _micro_confusion_signals(
    student_text: str, eval_result: dict
) -> tuple[bool, bool, bool]:
    """
    Non-keyword confusion classifier:
      - low confidence: short / hedged response + low score
      - incorrect idea: low correctness signal by evaluator
      - incomplete understanding: explicit missing points from evaluator
    """
    score = int(eval_result.get("score", 0) or 0)
    correct = bool(eval_result.get("correct"))
    missing = _micro_read_missing_points(eval_result)
    text = (student_text or "").strip()
    words = len(text.split())
    low_confidence = score < 50 or (words <= 5 and score < 60)
    incorrect_idea = (not correct and score < 65)
    incomplete_understanding = bool(missing) or (
        score < 72 and not _micro_has_reasoning_or_connection(text)
    )
    return low_confidence, incorrect_idea, incomplete_understanding


def _apply_micro_sus_adjustment(
    session: Session,
    *,
    score: int,
    correct: bool,
    missing_points: list[str],
) -> None:
    # Micro-teaching SUS adjustment (lightweight, not mastery-level)
    current_sus = float(getattr(session, "sus_score", 50.0) or 50.0)
    delta = 0.0

    if correct:
        if score >= 75 and not missing_points:
            delta = 2.0
        else:
            delta = 1.0
    else:
        if score < 45 or bool(missing_points):
            delta = -1.0
        else:
            delta = 0.0

    session.sus_score = round(max(0.0, min(100.0, current_sus + delta)), 1)


def should_run_micro_teaching(
    session: Session, *, ignore_opening_claim: bool = False
) -> bool:
    """
    True when the session should use the short interactive micro-loop instead of
    one long RAG explanation on the next idle teach turn.
    """
    if not _is_teacher_progression(session):
        return False
    if getattr(session, "explanation_mode", None) == "six_step":
        return False
    # Micro-teaching is the Zone 1/2 VTSE main-teaching loop.
    if int(getattr(session, "current_zone", 0) or 0) not in (1, 2):
        return False
    step = int(getattr(session, "current_step_in_concept", 0) or 0)
    if step >= MICRO_TEACH_STEP_READY_QUIZ:
        return False
    if not ignore_opening_claim:
        from app.services.pedagogy import vtse_opening_claim

        # Starting or already-delivered opening for this concept must never
        # re-enter teacher_micro_teaching_opening via idle auto-explain.
        if vtse_opening_claim.is_opening_claimed_or_ready(session):
            return False
    return True


async def _micro_build_rag_context(
    ctx: HandlerContext,
    session: Session,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> tuple[RAGService, str, Optional[Any], Topic | TeacherTopic | None]:
    """Shared context build for micro-teaching LLM calls (VTSE template outline)."""
    from app.models.identification.student_profiles import StudentProfile
    from app.services.curriculum.concept_vtse_context import load_concept_vtse_rag_context
    from app.services.session_concept_tracking import session_concept_id_for_rag

    topic_note_repository = TopicNoteRepository()
    video_subtitle_repository = VideoSubtitleRepository()
    topic_question_repository = TopicQuestionRepository()
    rag_service = RAGService(
        topic_note_repository,
        video_subtitle_repository,
        topic_question_repository,
        ctx.topic_repository,
    )
    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    topic_id = session.topic_id
    concept_id = session_concept_id_for_rag(session)
    concept_label = (getattr(session, "current_concept", None) or "").strip()

    # Prefer authored VTSE template outline over TopicNotes for concept teaching chat.
    context = await load_concept_vtse_rag_context(
        concept_id,
        concept_label=concept_label,
    )
    if not (context or "").strip():
        # Soft empty context when template missing (publish gate should prevent this).
        context = (
            f"Concept: {concept_label or 'current concept'}\n"
            "No authored VTSE template outline is available for this concept."
        )

    topic_for_prompt = await _get_topic_or_teacher_topic_impl(
        topic_id, ctx.topic_repository
    )
    return rag_service, context or "", student_profile, topic_for_prompt


async def teacher_micro_teaching_opening(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> str | dict[str, Any]:
    """
    First turn for a concept: one short hook + a single familiarity / guess question.
    Sets current_step_in_concept=0 and current_question to the assistant message.
    """
    event_repository = EventRepository()
    rag_service, context, student_profile, topic_for_prompt = await _micro_build_rag_context(
        ctx, session, student_id, topic
    )
    cc = (getattr(session, "current_concept", None) or "").strip() or "(concept)"
    topic_name = topic_for_prompt.topic_name if topic_for_prompt else "this topic"
    start_time = time.time()
    sus_score = float(getattr(session, "sus_score", 50.0) or 50.0)
    if sus_score < 40.0:
        sus_level = "LOW"
        sus_instruction = (
            "SUS ADAPTATION — LOW (<40):\n"
            "- Student is struggling: keep language very simple and concrete.\n"
            "- Add a tiny supportive cue (e.g., 'Let's break this into a simple idea').\n"
            "- If you include explanation, keep it clear and short (2-3 short sentences max).\n"
            "- Ask exactly ONE easier question that checks a basic understanding step.\n"
            "BLOOM QUESTION DEPTH — LOW:\n"
            "- Frame the single question as recall/basic understanding.\n"
            "- Prefer prompts like 'what is...', 'which one...', or 'what is this called?'.\n"
            "- Avoid why/how-reasoning and avoid multi-step logic.\n"
        )
    elif sus_score > 70.0:
        sus_level = "HIGH"
        sus_instruction = (
            "SUS ADAPTATION — HIGH (>70):\n"
            "- Student is confident: avoid over-explaining and avoid repeating basics.\n"
            "- Keep explanation minimal (1-2 short sentences max).\n"
            "- Ask exactly ONE deeper question emphasizing why/how or conceptual connection.\n"
            "BLOOM QUESTION DEPTH — HIGH:\n"
            "- Frame the single question as reasoning/connection.\n"
            "- Prefer prompts like 'why does...', 'how does this connect...', or "
            "'what would happen if...'.\n"
            "- Avoid basic fact-recall questions.\n"
        )
    else:
        sus_level = "MEDIUM"
        sus_instruction = (
            "SUS ADAPTATION — MEDIUM (40-70):\n"
            "- Use balanced current behavior: brief explanation + one follow-up question.\n"
            "- Keep clarity and pacing steady.\n"
            "BLOOM QUESTION DEPTH — MEDIUM:\n"
            "- Frame the single question as understanding + simple application.\n"
            "- Prefer prompts like 'how does...', or 'what happens if one part is missing?'.\n"
            "- Avoid very abstract or multi-step deep reasoning.\n"
        )
    user_prompt = (
        "You are a warm classroom teacher using a short interactive style.\n"
        "ZONE 1 — MAIN TEACHING (micro-loop opening).\n"
        f"Topic: {topic_name}. Focus concept: **{cc}**.\n"
        f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
        "Curriculum notes (may be brief):\n"
        f"{(context or '')[:2800]}\n\n"
        f"{_MICRO_CALM_BREVITY}"
        f"{sus_instruction}"
        "TASK — OPENING ONLY:\n"
        "- At most ONE short optional hook (half a sentence), then ONE simple question—"
        "no mini-lesson.\n"
        "- In a few words, say you'll connect ideas in small steps.\n"
        "- Do NOT fully explain the concept yet. No bullet lists.\n"
        "- End with your question clearly.\n"
        "Maximum 3 short sentences total."
    )
    try:
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.QUESTION,
                "content": user_prompt[:4000],
                "timestamp": datetime.utcnow(),
            }
        )
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
    sp_dict = student_profile.model_dump() if student_profile else None
    boundary = _rag_prompt_boundary_kwargs(session, topic_for_prompt)
    answer = ""

    try:
        answer = await rag_service.generate_prompt(
            question=f"{user_prompt}{PLAIN_TEXT_REPLY_SUFFIX}",
            context=context or "No notes provided; stay general and conservative.",
            student_profile=sp_dict,
            topic_name=topic_name,
            learning_state="explaining",
            user_intent="EXPLAIN",
            current_concept=cc,
            **boundary,
        )
    except Exception:  # noqa: BLE001
        answer = ""

    # Execution-path safety: never allow a prompt branch without an LLM generation attempt.
    if not answer or not str(answer).strip():
        fallback_prompt = (
            "Ask exactly ONE short Socratic question about the current concept. "
            "Do not explain the concept and do not reveal the answer."
            if mc_action == "probe"
            else "Give a very short response for the current concept and end with one clear follow-up question."
        )
        try:
            answer = await rag_service.generate_prompt(
                question=f"{fallback_prompt}{PLAIN_TEXT_REPLY_SUFFIX}",
                context=context or "No notes provided; stay general and conservative.",
                student_profile=sp_dict,
                topic_name=topic_name,
                learning_state="explaining",
                user_intent="EXPLAIN",
                current_concept=cc,
                **boundary,
            )
        except Exception:  # noqa: BLE001
            answer = ""
    answer = _coerce_rag_answer(answer)
    if not answer:
        answer = (
            f"Before we dive into **{cc}**, what do you already think it might mean?"
        )
    answer = _micro_ensure_engagement_closer(answer)
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        return {"message": answer}
    session.explained_points = []
    # Taught points derived from concept content, not generated text
    derived = _derive_taught_points_from_micro_context(cc, context or "")
    kc = _session_key_concepts_for_clusters(session, topic_for_prompt)
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if clusters and flat_index_is_first_in_its_cluster(idx, clusters):
        session.cluster_taught_points = []
    session.taught_points = list(derived)
    session.cluster_taught_points = _dedupe_ordered_taught_points(
        list(getattr(session, "cluster_taught_points", []) or []) + derived,
        cap=24,
    )
    # Topic aggregation uses per-concept derived points (avoid cluster duplication)
    session.topic_taught_points = _dedupe_ordered_taught_points(
        list(getattr(session, "topic_taught_points", []) or []) + list(derived),
        cap=60,
    )
    session.current_step_in_concept = 0
    session.current_concept_correct_count = 0
    session.current_concept_mastered = False
    session.micro_last_connection_round = -1
    session.current_question = answer[:5000]
    session.flow_state = "explaining"
    session.learning_state = "explaining"
    session.last_question = user_prompt[:4000]
    session.last_answer = answer
    # ── VTSE Zone 1 board ────────────────────────────────────────────────────────
    # Build the VTSE timeline BEFORE session.save() so zone1_timeline_cache is
    # persisted in the same write as the rest of the micro-teaching state.
    _out: dict[str, Any] = {"message": answer}
    logger.info(
        "[VTSE_ZONE1] MICRO_OPENING_ENTERED concept=%s zone=%s",
        cc,
        int(getattr(session, "current_zone", 0) or 0),
    )
    try:
        from app.services.timeline_planner_v3 import TimelinePlannerV3
        from app.services.handlers.zone1_timeline_finalize import (
            finalize_zone1_tutor_payload,
        )
        _vtse_planner = TimelinePlannerV3()
        _topic_name_str = (
            topic_for_prompt.topic_name
            if topic_for_prompt is not None
            else "this topic"
        )
        _out = await finalize_zone1_tutor_payload(
            session,
            _out,
            beat_kind="opening",
            topic_name=_topic_name_str,
            concept=cc,
            question=f"Explain {cc}",
            planner=_vtse_planner,
            rag_service=rag_service,
            cir_rag_context=context,
            student_profile_dict=None,
        )
        _itv3_ok = isinstance(_out.get("instruction_timeline_v3"), dict)
        logger.info(
            "[VTSE_ZONE1] TIMELINE_ATTACHED=%s planner_source=%s beat_count=%s",
            _itv3_ok,
            _out.get("planner_source", "none"),
            len((_out.get("instruction_timeline_v3") or {}).get("beats") or []),
        )
    except Exception as _vtse_exc:  # noqa: BLE001
        logger.warning(
            "[VTSE_ZONE1] MICRO_OPENING_TIMELINE_ATTACH_FAILED error=%s", str(_vtse_exc)[:500]
        )
    # Arm structured concept questions (DB first) — replaces opening hook question.
    try:
        from app.services.handlers.concept_question_orchestrator import (
            arm_concept_questions_after_opening,
        )
        from app.services.pedagogy.concept_teaching_orchestrator import (
            ConceptTeachingOrchestrator,
        )

        _cto = ConceptTeachingOrchestrator()
        # Snapshot may already exist from session idle path; ensure anyway.
        try:
            await _cto.ensure_sequence_snapshot(session)
        except Exception:  # noqa: BLE001
            logger.warning("[CONCEPT_TEACH] snapshot_before_opening_failed", exc_info=True)
        defer_questions = _cto.mark_vtse_opening_started(session)
        if defer_questions:
            logger.info(
                "[CONCEPT_TEACH] defer_concept_questions concept=%s (VTSE timeline must play)",
                cc,
            )
            session.flow_state = "explaining"
            # Opening text must not look like a pending micro-question — that sets
            # micro_quiz_hold and blocks the FE from finishing the timeline.
            session.current_question = None
            session.concept_questions_active = False
            _out["concept_teaching_await_vtse_done"] = 1
            timeline = _out.get("instruction_timeline_v3")
            beats = timeline.get("beats") if isinstance(timeline, dict) else None
            if isinstance(beats, list) and beats:
                # The timeline's first narration is the voice. The micro-opening
                # question must not speak beside it. Taught points stay derived.
                _out["message"] = ""
        else:
            await arm_concept_questions_after_opening(
                ctx, session, session_id, student_id, topic
            )
            _out["message"] = (
                f"Let's explore **{cc}** together. "
                "Follow along on the board — when you're ready, answer the question in chat."
            )
    except Exception as _cq_exc:  # noqa: BLE001
        logger.warning("[CONCEPT_Q] arm_failed error=%s", str(_cq_exc)[:300])
    # One save: micro-teaching state + zone1_timeline_cache together
    await session.save()
    response_time_ms = int((time.time() - start_time) * 1000)
    await AIGenerationLog(
        organization_id=session.organization_id,
        student_id=student_id,
        topic_id=session.topic_id,
        session_id=session_id,
        model_used=Settings.DEEPSEEK_MODEL,
        task_type="qa",
        tokens_used=0,
        estimated_cost=0,
        response_time_ms=response_time_ms,
    ).insert()
    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.ANSWER,
            "content": answer[:4000],
            "timestamp": datetime.utcnow(),
        }
    )
    return _out


async def teacher_micro_teaching_process_reply(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    student_text: str,
) -> str | dict[str, Any]:
    """
    Handle one student reply during micro-teaching: evaluate with ``missing_points``,
    then continue teaching until main ideas are covered (or strong paraphrase) with a
    substantive answer — never on score alone. At least one guided follow-up after
    the opening beat is required before quiz handoff. Step counter is only a safety
    cap (``MICRO_TEACH_MAX_LOOPS``), not the primary progression signal.
    """
    start_time = time.time()
    event_repository = EventRepository()
    rag_service, context, student_profile, topic_for_prompt = await _micro_build_rag_context(
        ctx, session, student_id, topic
    )
    live_s = await ctx.session_repository.get_by_id(session_id)
    if live_s is not None:
        session = live_s
    cc = (getattr(session, "current_concept", None) or "").strip() or "(concept)"
    last_q = (getattr(session, "current_question", None) or "").strip()
    prev_rounds = int(getattr(session, "current_step_in_concept", 0) or 0)
    topic_name = topic_for_prompt.topic_name if topic_for_prompt else "this topic"
    sus_score = float(getattr(session, "sus_score", 50.0) or 50.0)
    if sus_score < 40.0:
        sus_level = "LOW"
        sus_instruction = (
            "SUS ADAPTATION — LOW (<40):\n"
            "- Student is struggling: simplify language and avoid jumps.\n"
            "- Explain with clear, concrete steps (2-3 short sentences max).\n"
            "- Offer small guidance cues and ask exactly ONE easier question.\n"
            "BLOOM QUESTION DEPTH — LOW:\n"
            "- Ask one recall/basic-understanding question tied to the current concept.\n"
            "- Prefer 'what is...' or 'what is this process called?'.\n"
            "- Avoid why/how reasoning and avoid multi-step questions.\n"
        )
    elif sus_score > 70.0:
        sus_level = "HIGH"
        sus_instruction = (
            "SUS ADAPTATION — HIGH (>70):\n"
            "- Student is confident: keep explanation compact (1-2 short sentences max).\n"
            "- Do not repeat basics; push deeper reasoning.\n"
            "- Ask exactly ONE more challenging why/how/connection question.\n"
            "BLOOM QUESTION DEPTH — HIGH:\n"
            "- Ask one deeper reasoning/connection question.\n"
            "- Prefer 'why...', 'how does this connect...', or 'what would happen if...'.\n"
            "- Avoid basic recall questions.\n"
        )
    else:
        sus_level = "MEDIUM"
        sus_instruction = (
            "SUS ADAPTATION — MEDIUM (40-70):\n"
            "- Keep current balanced style: short explanation and one follow-up question.\n"
            "BLOOM QUESTION DEPTH — MEDIUM:\n"
            "- Ask one understanding/application question.\n"
            "- Prefer 'how does this work here?' or 'what happens if one piece is missing?'.\n"
            "- Avoid very deep abstract reasoning.\n"
        )

    if prev_rounds >= MICRO_TEACH_STEP_READY_QUIZ:
        return _micro_ensure_engagement_closer(
            "You've connected the main ideas here. In your own words, what is happening "
            "overall before we move on?"
        )

    eval_result: dict = {}
    try:
        eval_result = await _engine_evaluate_answer(
            cc,
            student_text,
            reference_context=context[:1200] if context else None,
        )
    except Exception:  # noqa: BLE001
        eval_result = {
            "correct": False,
            "score": 50,
            "feedback": "Thanks for sharing your thinking.",
            "missing_points": [],
        }

    score = int(eval_result.get("score", 0) or 0)
    fb = str(eval_result.get("feedback") or "").strip()
    mc_out = handle_misconception(eval_result, mode="micro", attempt=prev_rounds)
    mc_action = str(mc_out.get("action") or "probe")
    if mc_action not in {"confirm", "probe", "re_explain"}:
        mc_action = "probe"
    logger.info(
        "[MICRO_MISCONCEPTION] session_id=%s attempt=%s action=%s score=%s",
        str(session_id),
        prev_rounds,
        mc_action,
        score,
    )
    correct = mc_action == "confirm"
    missing = _micro_read_missing_points(eval_result)
    correct_count = int(getattr(session, "current_concept_correct_count", 0) or 0)
    if mc_action == "confirm" and not missing:
        correct_count += 1
    else:
        correct_count = 0
    session.current_concept_correct_count = correct_count
    if correct_count >= 2:
        session.current_concept_mastered = True
    elif correct_count == 0:
        session.current_concept_mastered = False
    missing_display = ", ".join(f'"{m}"' for m in missing[:5]) if missing else "(none)"
    explained_points = [
        str(p).strip().lower()
        for p in (getattr(session, "explained_points", None) or [])
        if str(p).strip()
    ]
    next_missing = [m for m in missing if str(m).strip().lower() not in set(explained_points)]
    next_missing_display = (
        ", ".join(f'"{m}"' for m in next_missing[:5]) if next_missing else "(none)"
    )

    meets = _micro_meets_concept_completion(eval_result, student_text)
    shallow = _micro_is_shallow_keyword_answer(student_text, eval_result)
    # Attempt progression safety: advance only on non-confirm.
    next_cycle = prev_rounds if mc_action == "confirm" else (prev_rounds + 1)
    safety_max = next_cycle >= MICRO_TEACH_MAX_LOOPS
    had_guided_followup = prev_rounds >= 1
    # True once the student has already received at least one deepening turn
    # (prev_rounds >= 2 means opening + connection + deepening all happened).
    had_deepening = prev_rounds >= 2
    low_conf, incorrect_idea, incomplete_understanding = _micro_confusion_signals(
        student_text, eval_result
    )
    confusion_now = low_conf or incorrect_idea or incomplete_understanding
    repeated_confusion = confusion_now and prev_rounds >= 2
    # Exit only on safety cap, repeated confusion, or after the student has
    # demonstrated mastery AND already received a deepening question.
    # Progression lock: only CONFIRM can close/advance the micro-loop.
    force_exit = (
        mc_action == "confirm"
        and (
            bool(getattr(session, "current_concept_mastered", False))
            or
            safety_max
            or repeated_confusion
            or (meets and had_guided_followup and had_deepening)
        )
    )
    # Minimum-rounds lock (Fix 2 / question-lock Fix 3):
    # Readiness-based exit is blocked until the student has completed at least 2 rounds.
    # This guarantees stages 0 (intro) and 1 (inputs) are always covered before closing.
    # Safety exits (safety_max, repeated_confusion) are unaffected.
    if prev_rounds < 2 and force_exit and not (safety_max or repeated_confusion):
        force_exit = False
    # Strong students: ask a deeper question instead of exiting at first readiness signal.
    deepening_branch = meets and had_guided_followup and not had_deepening and not force_exit

    last_conn = int(getattr(session, "micro_last_connection_round", -1) or -1)
    needs_connection = prev_rounds == 0 or (
        last_conn >= 0 and (prev_rounds - last_conn) >= 2
    )
    connection_branch = (not force_exit) and needs_connection

    readiness_note = (
        f"Readiness to move on: {meets}. Shallow/high-score mismatch: {shallow}. "
        f"Missing ideas: {missing_display}."
    )

    user_prompt = ""
    if mc_action == "probe":
        probe_instruction = (
            "Ask a simple question about the main idea."
            if prev_rounds <= 0
            else "Ask a more guiding, narrower question that constrains the student's thinking "
            "(for example: compare two choices, yes/no with reasoning, or one focused condition)."
        )
        user_prompt = (
            "ZONE 1 — SOCRATIC PROBE (misconception handling).\n"
            "You are a tutor helping the student self-correct.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Your last question was:\n{last_q}\n"
            f"The student answered:\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Missing ideas: {next_missing_display if next_missing else missing_display}\n"
            f"Use evaluator feedback lightly: {fb}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK — PROBE (acknowledge → micro-clarify → guide):\n"
            "- Optionally acknowledge the student's attempt in a short phrase.\n"
            "- Give a brief micro-clarification in 1-2 short sentences about the likely mistake or missing idea.\n"
            f"- {probe_instruction}\n"
            "- Ask EXACTLY ONE guiding question (must end with '?').\n"
            "- Keep the whole response concise: maximum 2-3 sentences total.\n"
            "- No long paragraph and do NOT reveal the full final answer.\n"
            f"- Do NOT repeat or paraphrase this previous question: {last_q}\n"
            "- Keep it warm, concise, and concept-focused."
        )
    elif mc_action == "re_explain":
        user_prompt = (
            "ZONE 1 — RE-EXPLAIN THEN CHECK (misconception handling).\n"
            "You are a tutor giving a concise recovery explanation.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Your last question was:\n{last_q}\n"
            f"The student answered:\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Missing ideas: {next_missing_display if next_missing else missing_display}\n"
            f"Use evaluator feedback lightly: {fb}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK — SHORT RE-EXPLAIN:\n"
            "- Briefly acknowledge their attempt.\n"
            "- Re-explain ONE small key idea in 1-3 short sentences.\n"
            "- Ask exactly ONE easier follow-up question.\n"
            "- Do NOT give a long lecture."
        )
    elif force_exit:
        exiting_on_ready = meets and had_guided_followup
        mastered_now = bool(getattr(session, "current_concept_mastered", False))
        if mastered_now:
            user_prompt = (
                "ZONE 1 — CONCEPT MASTERED CLOSURE.\n"
                "You are a human-like tutor: warm, specific, concise.\n"
                f"Topic: {topic_name}. Concept: **{cc}**.\n"
                f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
                f"The student just answered:\n{student_text}\n"
                f"Evaluator score (0–100): {score}. Missing ideas: {missing_display}.\n\n"
                "TASK — CLOSURE FORMAT (mandatory):\n"
                "1) One short confirmation line (e.g., 'Exactly — that's right.').\n"
                "2) One or two short reinforcement lines restating the key idea simply.\n"
                "3) One smooth transition line to the next stage/idea.\n"
                "Constraints:\n"
                "- Maximum 3 sentences total.\n"
                "- No long paragraph.\n"
                "- Do NOT repeat the full explanation.\n"
                "- Do NOT ask the same concept question again.\n"
                "- At most ONE optional question in the final sentence."
            )
        else:
            user_prompt = (
                "ZONE 1 — MAIN TEACHING (micro-loop CLOSE).\n"
                "You are a human-like tutor: warm, specific, not mechanical.\n"
                f"Topic: {topic_name}. Concept: **{cc}**.\n"
                f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
                f"Your last question was:\n{last_q}\n"
                f"The student answered (their own words):\n{student_text}\n"
                f"Evaluator score (0–100): {score}. {readiness_note}\n"
                f"Use evaluator feedback lightly: {fb}\n"
                f"Exiting on readiness: {exiting_on_ready}. Safety max rounds: {safety_max}.\n\n"
                f"{_MICRO_CALM_BREVITY}"
                f"{sus_instruction}"
                "TASK — HANDOFF (closing the micro-loop for this concept):\n"
                "- Briefly acknowledge the student's last answer (1 sentence, no over-praise).\n"
                "- Give a concise conceptual wrap-up of the concept in 2-3 sentences.\n"
                "- DO NOT ask a new micro question here — the student will enter a Q&A phase immediately after.\n"
                "- DO NOT say 'Any questions?' or 'Do you have questions?' — that prompt is added automatically.\n"
                "- If repeated confusion or safety max: give the correct idea briefly, no question.\n"
                "End with a warm, forward-looking closing sentence only (no question mark)."
            )
    elif connection_branch and prev_rounds == 0:
        user_prompt = (
            "ZONE 1 — CONNECTION BEAT (first reply after opening).\n"
            "You are a tutor building understanding step-by-step.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Curriculum notes:\n{(context or '')[:2200]}\n\n"
            f"You previously asked:\n{last_q}\n"
            f"The student answered:\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Broadly on track: {correct}.\n"
            f"Evaluator missing ideas (guide toward these; do not dump full answers): "
            f"{next_missing_display if next_missing else missing_display}\n"
            f"Already explained points in this concept (avoid repeating): {', '.join(explained_points[:6]) if explained_points else '(none)'}\n"
            f"Use evaluator feedback lightly: {fb}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK — CONNECTION PATTERN:\n"
            "- Explain one small meaningful idea in 1-3 concise sentences using missing ideas as guide rails.\n"
            "- Explicitly connect with prior learning, varying bridge language each turn.\n"
            "- Then ask one question that links ONLY the line you just explained to the current concept.\n"
            "- If confusion is visible, simplify wording and ask an easier question than last turn.\n"
            "- No lecture dump, no repeated question text."
        )
    elif connection_branch:
        user_prompt = (
            "ZONE 1 — PERIODIC CONNECTION (every few exchanges).\n"
            "You are a tutor who keeps weaving ideas together.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Curriculum notes:\n{(context or '')[:2200]}\n\n"
            f"You previously asked:\n{last_q}\n"
            f"The student answered:\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Broadly on track: {correct}.\n"
            f"Evaluator missing ideas: {next_missing_display if next_missing else missing_display}\n"
            f"Already explained points in this concept (avoid repeating): {', '.join(explained_points[:6]) if explained_points else '(none)'}\n"
            f"Use evaluator feedback lightly: {fb}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK — CONNECTION CHECK:\n"
            "- Explain one small meaningful idea in 1-3 concise sentences.\n"
            "- Explicitly chain ideas with varied natural phrasing (avoid repeating the same bridge).\n"
            "- Then ask one local question derived only from your latest explanation sentence.\n"
            "- If confusion is visible, use simpler language and make the question easier.\n"
            "- Avoid repeated praise and avoid reusing the same question."
        )
    elif deepening_branch:
        user_prompt = (
            "ZONE 1 — DEEPENING (student shows strong understanding).\n"
            "You are a tutor who challenges the student to think further within the same concept.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Curriculum notes:\n{(context or '')[:2200]}\n\n"
            f"You previously asked:\n{last_q}\n"
            f"The student answered (showing strong understanding):\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Student is ready for deeper thinking.\n"
            f"Already explained points in this concept (avoid repeating): {', '.join(explained_points[:6]) if explained_points else '(none)'}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK — DEEPENING (do NOT exit — keep the student in the teaching loop):\n"
            "1) Acknowledge their understanding briefly (no over-praise).\n"
            "2) Introduce ONE deeper aspect or implication of **this same concept** — not a new concept.\n"
            "   Examples: an edge case, an underlying mechanism, a real-world consequence, or a 'what if' scenario.\n"
            "3) Ask ONE probing question that requires the student to apply or extend this deeper idea.\n"
            "4) Stay strictly within the current concept — no future concepts, no topic jumps.\n"
            "Do NOT summarize or hand off — the teaching continues."
        )
    else:
        user_prompt = (
            "ZONE 1 — SOCRATIC CHAIN (acknowledge → extend → connect → ask).\n"
            "Never ask a question that ignores what they just said.\n"
            f"Topic: {topic_name}. Concept: **{cc}**.\n"
            f"Student SUS score: {sus_score:.1f} ({sus_level}).\n"
            f"Curriculum notes:\n{(context or '')[:2200]}\n\n"
            f"You previously asked:\n{last_q}\n"
            f"The student answered:\n{student_text}\n"
            f"Evaluator score (0–100): {score}. Broadly on track: {correct}.\n"
            f"Evaluator missing ideas (steer gently if non-empty): {next_missing_display if next_missing else missing_display}\n"
            f"Already explained points in this concept (avoid repeating): {', '.join(explained_points[:6]) if explained_points else '(none)'}\n"
            f"Use evaluator feedback lightly: {fb}\n\n"
            f"{_MICRO_CALM_BREVITY}"
            f"{sus_instruction}"
            "TASK:\n"
            "1) Briefly acknowledge their idea (no over-praise).\n"
            "2) Explain one small meaningful idea clearly in 1-3 sentences.\n"
            "3) Add an explicit bridge to prior steps with varied wording (do not reuse the same bridge each turn).\n"
            "4) Ask one local question that naturally follows from only your last explanation line.\n"
            "5) If confusion is visible, simplify and ask an easier follow-up.\n"
            "Do not repeat the previous question."
        )

    # Guard: ensure a prompt always exists for any action/branch combination.
    if not user_prompt.strip():
        user_prompt = (
            f"{_MICRO_CALM_BREVITY}"
            "Ask exactly ONE short Socratic follow-up question tied to the student's last reply."
        )

    # Fix 1 — Semantic stage injection:
    # Prepend the stage instruction to non-exit turns so each round covers a distinct
    # aspect of the concept (intro → inputs → process → outcome), preventing repetition.
    # Stage is derived from prev_rounds without adding a new session field.
    if not force_exit and mc_action != "probe" and mc_action != "re_explain":
        _concept_stage = min(3, prev_rounds)
        user_prompt = (
            f"{_STAGE_INSTRUCTIONS[_concept_stage]}\n\n"
            f"{user_prompt}"
        )

    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.QUESTION,
            "content": user_prompt[:4000],
            "timestamp": datetime.utcnow(),
        }
    )
    sp_dict = student_profile.model_dump() if student_profile else None
    boundary = _rag_prompt_boundary_kwargs(session, topic_for_prompt)
    try:
        answer = await rag_service.generate_prompt(
            question=f"{user_prompt}{PLAIN_TEXT_REPLY_SUFFIX}",
            context=context or "No notes provided; stay general and conservative.",
            student_profile=sp_dict,
            topic_name=topic_name,
            learning_state="explaining",
            user_intent="EXPLAIN",
            current_concept=cc,
            **boundary,
        )
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
        if mc_action == "probe":
            answer = "What part of your answer do you want to rethink?"
        else:
            answer = (
                "Let's simplify this one step. What part still feels unclear to you?"
            )
    answer = _coerce_rag_answer(answer)
    if not answer:
        answer = "Thanks — let's keep going. What part feels least clear so far?"
    expl_sentence_cap = _micro_adaptive_expl_sentence_cap(
        mc_action=mc_action,
        score=score,
        missing_points=missing,
    )
    if not force_exit:
        answer = _enforce_explain_then_one_question(
            answer,
            fallback_expl="Let's think about this together in a simple way.",
            max_expl_sentences=expl_sentence_cap,
        )
    if force_exit:
        answer = _micro_strip_questions_for_handoff(answer)
    else:
        answer = _micro_ensure_engagement_closer(answer)
    # Safety guard: micro-teaching must always return a visible response.
    if not answer or len(answer.strip()) == 0:
        answer = "What part of your answer do you want to rethink?"

    try:
        session = await ctx.session_repository.get_by_id(session_id)
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
        return {"message": answer}
    if session is None:
        return {"message": answer}
    _apply_micro_sus_adjustment(
        session,
        score=score,
        correct=correct,
        missing_points=missing,
    )
    if force_exit:
        session.current_step_in_concept = MICRO_TEACH_STEP_READY_QUIZ
        session.current_question = None
        # Q&A phase starts immediately after micro-teaching closes — before any quiz.
        session.student_questions_active = True
        session.student_questions_concept = cc
        session.flow_state = "waiting_for_question"
        session.current_mode = "student_questions"
    else:
        session.current_step_in_concept = next_cycle
        session.current_question = answer[:5000]
        # Track what the AI actually explained this turn (not evaluator missing_points).
        # This gives semantically meaningful repetition guard keys.
        new_point = _extract_core_teaching_point(answer)
        if new_point and new_point not in set(explained_points):
            session.explained_points = (explained_points + [new_point])[-5:]
        if connection_branch:
            session.micro_last_connection_round = prev_rounds
        session.flow_state = "explaining"
    session.learning_state = "explaining"
    session.last_question = user_prompt[:4000]
    session.last_answer = answer
    try:
        await session.save()
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
    response_time_ms = int((time.time() - start_time) * 1000)
    try:
        await AIGenerationLog(
            organization_id=session.organization_id,
            student_id=student_id,
            topic_id=session.topic_id,
            session_id=session_id,
            model_used=Settings.DEEPSEEK_MODEL,
            task_type="qa",
            tokens_used=0,
            estimated_cost=0,
            response_time_ms=response_time_ms,
        ).insert()
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
    try:
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.ANSWER,
                "content": answer[:4000],
                "timestamp": datetime.utcnow(),
            }
        )
    except Exception:  # noqa: BLE001
        logger.exception("MICRO_FLOW_ERROR", exc_info=True)
    # Fix 4: append Q&A prompt to the closing message when micro-teaching exits.
    # Q&A must happen before any cluster quiz — the student sees the invitation here.
    if force_exit:
        answer = answer + f"\n\nDo you have any questions about **{cc}** before we move on?"
    return {"message": answer}


async def teacher_explain_turn(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    rag_question: str,
    *,
    intent: str,
    state_at_entry: str,
    next_flow_state: str,
    next_learning_state: str | None,
) -> str | dict | None:
    """Log QUESTION, run RAG, set flow_state. Returns None if context too thin."""
    from app.models.identification.student_profiles import StudentProfile

    event_repository = EventRepository()
    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.QUESTION,
            "content": rag_question[:4000] if len(rag_question) > 4000 else rag_question,
            "timestamp": datetime.utcnow(),
        }
    )
    topic_note_repository = TopicNoteRepository()
    video_subtitle_repository = VideoSubtitleRepository()
    topic_question_repository = TopicQuestionRepository()
    rag_service = RAGService(
        topic_note_repository,
        video_subtitle_repository,
        topic_question_repository,
        ctx.topic_repository,
    )
    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    teaching_style = (
        student_profile.preferred_teaching_style
        if student_profile is not None
        else None
    )
    interests = student_profile.interests if student_profile is not None else []
    interest_category = interests[0] if interests else "general"
    difficulty_level = (
        student_profile.preferred_depth if student_profile is not None else None
    )

    # ── Phase 6: Spaced retrieval — detect & stamp a due concept ─────────────
    # One indexed query fetches all concept-level mastery rows for this
    # student × topic.  Filtering is in-memory so no further DB calls are
    # needed.  The retrieval prefix is computed here and applied to the final
    # response; it does NOT affect the concept being taught this turn.
    _retrieval_prefix: str | None = None
    _ret_concept: str | None = None  # initialised here so it is visible at save points
    try:
        _ret_repo = MasteryRepository()
        _ret_records = await _ret_repo.get_many(
            {
                "organization_id": session.organization_id,
                "student_id": student_id,
                "topic_id": session.topic_id,
                "concept": {"$ne": None},
            },
            limit=50,
        )
        _ret_now = datetime.utcnow()
        # Exclude the concept being taught right now and concepts already seen
        # this session to avoid redundancy and infinite repetition.
        _ret_exclude: set[str] = set(
            filter(None, getattr(session, "learned_concepts", []) or [])
        )
        _ret_current = getattr(session, "current_concept", None)
        if _ret_current:
            _ret_exclude.add(_ret_current)
        _due = get_due_concepts(_ret_records, _ret_now, exclude_concepts=_ret_exclude)
        _ret_concept = _due[0] if _due else None  # max 1 per turn
        if _ret_concept:
            _retrieval_prefix = (
                f"**Quick recall before we continue:** "
                f"Can you recall what **{_ret_concept}** means? "
                f"Take a moment to think about it before reading on.\n\n"
                f"*(When you're ready, today's explanation continues below.)*"
            )
            # Stamp last_reviewed_at so this concept is not surfaced again
            # until its review_interval_days have elapsed (no-loop guarantee).
            for _ret_rec in _ret_records:
                if getattr(_ret_rec, "concept", None) == _ret_concept:
                    _ret_rec.last_reviewed_at = _ret_now
                    await _ret_rec.save()
                    break
    except Exception:  # noqa: BLE001
        # Retrieval is additive; any failure must not block the explanation.
        _retrieval_prefix = None

    # ── Zone-specific pedagogy (teacher progression) ─────────────────────────
    _zone = int(getattr(session, "current_zone", 1) or 1)

    if _zone in (1, 2):
        rag_question = (
            rag_question
            + " ZONE 1 — MAIN TEACHING: Give a compact explanation (at most"
            + " 2 short paragraphs) plus ONE concrete example."
            + " End with ONE clear check-in question. Do NOT write a long essay"
            + " or multi-page lecture."
        )
    elif _zone == 3:
        rag_question = (
            rag_question
            + " ZONE 3 — CHALLENGE: Give a SHORT scenario or problem in plain language"
            + " (2–4 sentences max). Offer at most ONE hint as a question, not a solution."
            + " Ask the student what they predict and why. No step-by-step teaching."
        )
    elif _zone >= 4:
        rag_question = (
            rag_question
            + " ZONE 4 — REFLECTION / EXTENSION: No teaching blocks and no quiz-style"
            + " right-or-wrong items. Offer ONE open-ended prompt that invites limits,"
            + " counterexamples, failure modes, or real-world variation—e.g. where the"
            + " usual story might break down, when it would not work the same way, or"
            + " what would change the outcome. Gently challenge a default assumption once."
            + " Link to broader life or trade-offs where natural. Keep it warm and short."
        )

    # Engagement hook — light; skip heavy hooks in Zone 4 (reflection tone).
    clean_interests = [
        str(i).strip() for i in (interests or []) if i is not None and str(i).strip()
    ]
    if _zone < 4:
        if clean_interests:
            interests_str = ", ".join(clean_interests)
            rag_question = (
                rag_question
                + f" Optionally tie the hook lightly to interests: {interests_str}."
            )
        else:
            rag_question = (
                rag_question
                + " Start with a brief, concrete hook before the core reply."
            )

    _is_probe_prompt = ("PROBE ONLY" in rag_question) or (
        "Output EXACTLY ONE Socratic follow-up question and NOTHING else." in rag_question
    )
    if not _is_probe_prompt:
        rag_question = (
            rag_question
            + " Reply rules (mandatory):"
            + " You MUST include a short explanation before asking a question."
            + " Explanation must be 1-2 short sentences."
            + " Then ask EXACTLY ONE question relevant to that explanation."
            + " Do NOT produce question-only responses."
            + " Do NOT ask multiple questions."
            + " Keep total response concise (about 2-3 sentences) and avoid lecture tone."
            + PLAIN_TEXT_REPLY_SUFFIX
        )

    topic_id = session.topic_id
    from app.services.curriculum.concept_vtse_context import load_concept_vtse_rag_context
    from app.services.session_concept_tracking import session_concept_id_for_rag

    context = await load_concept_vtse_rag_context(
        session_concept_id_for_rag(session),
        concept_label=(getattr(session, "current_concept", None) or ""),
    )
    if not (context or "").strip():
        notes = await rag_service.get_topic_notes(
            topic_id=topic_id,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
            current_concept=getattr(session, "current_concept", None),
            user_query=rag_question,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        context = await rag_service.build_context(
            notes,
            topic_id=topic_id,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
    # Proceed even if context is empty — the RAG prompt already has a
    # "context is very limited, use general knowledge carefully" note built in.
    # Returning None here caused an infinite idle loop when no notes exist.
    context = context or ""
    session.flow_state = "explaining"
    await session.save()

    # ── Phase 4: Six-step mode ────────────────────────────────────────────────
    # When explanation_mode == "six_step" we bypass the LLM entirely and return
    # a structured template instead.  All session state transitions (flow_state,
    # learning_state) are applied identically to the standard path.
    if getattr(session, "explanation_mode", None) == "six_step":
        result = build_six_step_explanation(
            concept=getattr(session, "current_concept", None),
            student_profile=student_profile,
            context=context,
        )
        session = await ctx.session_repository.get_by_id(session_id)
        if session is not None:
            session.flow_state = next_flow_state
            if next_learning_state is not None:
                session.learning_state = next_learning_state
            if _retrieval_prefix and _ret_concept:
                session.retrieval_active = True
                session.retrieval_concept = _ret_concept
            await session.save()
        msg = _apply_retrieval_prefix(
            _retrieval_prefix, apply_zone_pedagogy(_zone, result)
        )
        out_dict: dict[str, Any] = {
            "type": "explanation",
            "message": str(msg).strip(),
            "current_concept": str(getattr(session, "current_concept", None) or ""),
        }
        return out_dict
    # ── Standard RAG path (unchanged) ────────────────────────────────────────

    topic_for_prompt = await _get_topic_or_teacher_topic_impl(topic_id, ctx.topic_repository)
    out = await generate_tutor_rag_reply(
        session,
        session_id,
        student_id,
        rag_question,
        topic_id,
        intent,
        state_at_entry,
        topic_for_prompt,
        rag_service,
        context,
        student_profile,
        event_repository,
    )
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        # Phase 5 + 6: pedagogy suffix, then retrieval prefix (rare early-exit).
        # Cannot arm retrieval_active when session reload failed — skip silently.
        _out_final = out
        if isinstance(_out_final, str) and not _is_probe_prompt:
            _out_final = _enforce_explain_then_one_question(
                _out_final,
                fallback_expl="Let's build this step by step.",
            )
        msg = _apply_retrieval_prefix(
            _retrieval_prefix, apply_zone_pedagogy(_zone, _out_final)
        )
        out_dict: dict[str, Any] = {
            "type": "explanation",
            "message": str(msg).strip(),
            "current_concept": str(getattr(session, "current_concept", None) or ""),
        }
        return out_dict
    session.flow_state = next_flow_state
    if next_learning_state is not None:
        session.learning_state = next_learning_state
    # Phase 7: arm one-turn retrieval interaction.
    if _retrieval_prefix and _ret_concept:
        session.retrieval_active = True
        session.retrieval_concept = _ret_concept
    await session.save()
    # Phase 5 + 6: zone pedagogy suffix, then retrieval prefix.
    _out_final = out
    if isinstance(_out_final, str) and not _is_probe_prompt:
        _out_final = _enforce_explain_then_one_question(
            _out_final,
            fallback_expl="Let's build this step by step.",
        )
    msg = _apply_retrieval_prefix(
        _retrieval_prefix, apply_zone_pedagogy(_zone, _out_final)
    )
    out_dict: dict[str, Any] = {
        "type": "explanation",
        "message": str(msg).strip(),
        "current_concept": str(getattr(session, "current_concept", None) or ""),
    }
    # ── VTSE Zone 1 board ─────────────────────────────────────────────────────
    # Attach instruction_timeline_v3 for the FE ProductionTimelineRuntimeView.
    # NOTE: The primary zone-1 teaching path (micro-teaching opening) already
    # calls finalize_zone1_tutor_payload inside teacher_micro_teaching_opening.
    # This block covers the non-micro path (e.g. six_step mode or late-stage
    # explain turns where should_run_micro_teaching is False).
    if _zone in (1, 2):
        try:
            from app.services.timeline_planner_v3 import TimelinePlannerV3
            from app.services.handlers.zone1_timeline_finalize import (
                finalize_zone1_tutor_payload,
            )
            _vtse_planner = TimelinePlannerV3()
            out_dict = await finalize_zone1_tutor_payload(
                session,
                out_dict,
                beat_kind="explain_turn",
                topic_name=str(getattr(topic, "topic_name", None) or ""),
                concept=str(getattr(session, "current_concept", None) or ""),
                question=rag_question,
                planner=_vtse_planner,
                rag_service=rag_service,
                cir_rag_context=context,
                student_profile_dict=None,
            )
            _itv3_ok = isinstance(out_dict.get("instruction_timeline_v3"), dict)
            logger.info(
                "[VTSE_ZONE1] TIMELINE_ATTACHED=%s planner_source=%s",
                _itv3_ok,
                out_dict.get("planner_source", "none"),
            )
        except Exception as _vtse_exc:  # noqa: BLE001
            logger.warning("[VTSE_ZONE1] TIMELINE_ATTACH_FAILED error=%s", _vtse_exc)
    return out_dict


async def teacher_advance_skip(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict:
    """
    Advance past the current concept (skip).  Blocked if not yet mastered.
    On success, auto-explains the next concept.
    """
    if not getattr(session, "current_concept_mastered", False):
        return {
            "type": "blocked",
            "message": "Let's make sure you understand this concept first before moving ahead.",
            "current_concept": session.current_concept or "",
            "buttons": teacher_buttons(
                [
                    ("understand", "I understand"),
                    ("ask_question", "I have a question"),
                    ("explain_again", "Explain again"),
                ]
            ),
        }

    idx = int(session.current_concept_index or 0)
    session.current_concept_index = idx + 1
    session.current_concept_correct_count = 0
    session.current_concept_mastered = False
    if session.current_concept_index >= session.total_concepts:
        from app.services.session_concept_tracking import sync_session_concept_fields

        sync_session_concept_fields(session)
        session.current_concept = None
        session.current_concept_id = None
        coordinator = ZoneTransitionCoordinator()
        payload = await coordinator.resolve_after_teachback_slice(
            session,
            topic_done=True,
            default_complete_message=(
                "Excellent — you've worked through this session! Really well done. 🌟"
            ),
        )
        await session.save()
        _teacher_debug_flow(session, topic)
        if payload.get("type") != "_continue":
            return {
                "type": "explanation",
                "message": str(payload.get("message") or ""),
                "current_concept": "",
            }
        return {
            "type": "explanation",
            "message": (
                "You've completed this session slice. Great work! 🌟"
            ),
            "current_concept": "",
        }

    cc = _get_current_concept(session, topic)
    from app.services.session_concept_tracking import sync_session_concept_fields

    sync_session_concept_fields(session)
    cc = session.current_concept or cc
    session.current_step_in_concept = 0
    session.current_concept_correct_count = 0
    session.current_concept_mastered = False
    session.micro_last_connection_round = -1
    session.current_question = None
    session.cluster_check_pending = False
    session.cluster_check_concepts = None
    session.zone_round_successes = 0
    session.flow_state = "idle"
    await session.save()
    _teacher_debug_flow(session, topic)

    # Auto-explain the next concept immediately — no "start" prompt required.
    rag_q = (
        f'Please explain the concept "{cc}" clearly with a simple definition, '
        "example, and short summary."
    )
    body = await teacher_explain_turn(
        ctx,
        session,
        session_id,
        student_id,
        topic,
        rag_q,
        intent="EXPLAIN",
        state_at_entry="explaining",
        next_flow_state="explaining",
        next_learning_state="explaining",
    )
    if body is None:
        return {
            "type": "explanation",
            "message": "I don't have enough information on this concept yet.",
            "current_concept": cc,
        }
    if isinstance(body, dict):
        return body
    session = await ctx.session_repository.get_by_id(session_id)
    return {
        "type": "explanation",
        "message": str(body).strip(),
        "current_concept": cc,
    }
