"""
Zone 1 post-VTSE concept question loop — orchestration only.

After the main VTSE explanation for a key concept:
  • Up to 3 questions per concept (DB first, AI fallback)
  • Correct → brief praise in chat, auto-advance to next question (no buttons)
  • Wrong → short whiteboard explanation, then confusion loop with 2 buttons only
  • Does not modify VTSE authoring, CIR, or flow checkpoint runtime.
"""

from __future__ import annotations

import logging
import random
import re
from typing import TYPE_CHECKING, Any

from beanie.odm.fields import PydanticObjectId

from app.core.constants import CONCEPT_QUESTIONS_PER_CONCEPT, TEACHBACK_PASS_THRESHOLD
from app.repositories.event_repository import EventRepository
from app.services.evaluation_engine import evaluate_answer as _engine_evaluate_answer
from app.services.handlers.concept_taught_context import (
    answer_contradicts_lesson,
    build_correct_answer_message,
    build_taught_context,
    clean_db_answer_for_display,
    effective_taught_item_count,
    format_grading_context_block,
    format_taught_context_block,
    is_step_count_question,
    parse_numeric_tokens,
    question_asks_about_process_step,
    question_expects_single_item,
    resolve_reference_for_question,
    taught_content_supports_answer,
)
from app.services.handlers.teaching_transcript_service import (
    build_concept_quiz_taught_context,
    format_transcript_taught_block,
)
from app.services.handlers.text_only_reply import coerce_plain_text_reply
from app.services.handlers.cluster_utils import flat_index_is_last_in_its_cluster, resolve_clusters
from app.services.handlers.explanation_handler import (
    _get_topic_or_teacher_topic_impl,
    _micro_build_rag_context,
    generate_tutor_rag_reply,
    teacher_buttons,
)
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.rag_service import RAGService
from app.models.identification.student_profiles import StudentProfile


if TYPE_CHECKING:
    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)

_PRAISE = [
    "That's right — nice work.",
    "Exactly — you've got it.",
    "Yes, that's the idea.",
    "Good thinking — that's correct.",
]

_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}", re.I)


async def _concept_check_board_rag_bundle(
    ctx: HandlerContext,
    session: Session,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    taught_ctx: dict[str, Any] | None = None,
    session_id: PydanticObjectId | None = None,
) -> tuple[RAGService, str, Any | None, Topic | TeacherTopic | None]:
    """
    Tutor LLM bundle for concept-check replies.

    Context is the session board taught pack only — never the authored VTSE
    template outline — so praise / wrong explain / clarify cannot invent
    off-board facts from the template.
    """
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
    if taught_ctx is None and session_id is not None:
        taught_ctx = await build_concept_quiz_taught_context(session_id, session)
    taught_ctx = taught_ctx or {}
    context = (
        format_grading_context_block(taught_ctx)
        or format_transcript_taught_block(taught_ctx)
        or "No board lesson content recorded for this concept."
    )
    topic_for_prompt = await _get_topic_or_teacher_topic_impl(
        session.topic_id, ctx.topic_repository
    )
    if topic_for_prompt is None:
        topic_for_prompt = topic
    return rag_service, context, student_profile, topic_for_prompt


def is_concept_questions_mode(session: Session) -> bool:
    return bool(getattr(session, "concept_questions_active", False))


def is_concept_notes_mode(session: Session) -> bool:
    return bool(getattr(session, "concept_notes_active", False))


def _log_concept_confusion(session: Session, entry: str) -> None:
    text = (entry or "").strip()
    if not text:
        return
    log = list(getattr(session, "concept_question_confusion_log", None) or [])
    log.append(text[:500])
    session.concept_question_confusion_log = log[-12:]


def _fallback_concept_notes_markdown(
    concept: str,
    taught_ctx: dict[str, Any],
    confusions: list[str],
) -> str:
    cc = (concept or "Key concept").strip()
    lines = [f"## {cc}", ""]
    points = list(taught_ctx.get("taught_points") or [])
    steps = list(taught_ctx.get("steps") or [])
    for item in (points or steps)[:6]:
        s = str(item).strip()
        if s:
            lines.append(f"- {s}")
    if len(lines) <= 2:
        lines.append(f"- Main ideas from **{cc}** as covered in this lesson.")
    if confusions:
        lines.extend(["", "### Watch out", ""])
        for c in confusions[:3]:
            lines.append(f"- {c[:200]}")
    return "\n".join(lines)


async def _generate_concept_notes_markdown(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    concept: str,
) -> str:
    cc = (concept or "").strip() or "this concept"
    taught_ctx = build_taught_context(session)
    taught_block = format_taught_context_block(taught_ctx)
    confusions = list(getattr(session, "concept_question_confusion_log", None) or [])

    confusion_block = ""
    if confusions:
        confusion_block = (
            "STUDENT CONFUSIONS DURING CONCEPT CHECK:\n"
            + "\n".join(f"- {c}" for c in confusions)
            + "\n\n"
        )

    rag_question = (
        f'Create concise study notes for the key concept "{cc}".\n\n'
    )
    if taught_block:
        rag_question += (
            "WHAT WAS TAUGHT ON THE BOARD (authoritative — use ONLY this):\n"
            f"{taught_block}\n\n"
        )
    if confusion_block:
        rag_question += confusion_block

    rag_question += (
        "Write medium-length notes (about 120–220 words) in markdown:\n"
        f"## {cc}\n"
        "- 4–6 bullet points covering the most important ideas taught\n"
        "- If confusions exist, add a short \"### Watch out\" subsection with 1–3 bullets "
        "that directly address those mistakes\n\n"
        "Rules:\n"
        "- Plain markdown only — headings, bullets, bold for key terms\n"
        "- Accurate to taught content only; no invented facts\n"
        "- No quiz questions, no fluff, no tutor voice\n"
        "- Keep it scannable for a student reviewing before the next concept"
    )

    try:
        rag_service, context, student_profile, topic_for_prompt = await _micro_build_rag_context(
            ctx, session, student_id, topic
        )
        answer = await generate_tutor_rag_reply(
            session,
            session_id,
            student_id,
            rag_question,
            session.topic_id,
            "UNKNOWN",
            "explaining",
            topic_for_prompt,
            rag_service,
            context,
            student_profile,
            EventRepository(),
            persist_session_qa=False,
        )
        md = coerce_plain_text_reply((answer or "").strip())
        if md and len(md.split()) >= 25 and ("##" in md or md.count("- ") >= 3):
            return md[:8000]
    except Exception:  # noqa: BLE001
        logger.exception("[CONCEPT_NOTES] LLM generation failed concept=%s", cc)

    return _fallback_concept_notes_markdown(cc, taught_ctx, confusions)


async def _advance_after_concept_notes(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    """Move to the next key concept or cluster quiz after notes are dismissed."""
    kc = [
        str(c).strip()
        for c in (getattr(session, "key_concepts", None) or [])
        if str(c).strip()
    ]
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    at_cluster_end = flat_index_is_last_in_its_cluster(idx, clusters)

    if at_cluster_end:
        session.flow_state = "explaining"
        session.learning_state = "explaining"
        from app.core.constants import MICRO_TEACH_STEP_READY_QUIZ

        session.current_step_in_concept = MICRO_TEACH_STEP_READY_QUIZ
        await session.save()
        return {
            "type": "feedback",
            "message": "Great work on this concept! Let's put these ideas together.",
            "correct": True,
            "current_concept": session.current_concept or "",
        }

    session.current_concept_index = idx + 1
    from app.services.session_concept_tracking import sync_session_concept_fields

    sync_session_concept_fields(session)
    new_idx = int(session.current_concept_index)
    session.current_step_in_concept = 0
    session.micro_last_connection_round = -1
    session.flow_state = "idle"
    session.learning_state = "explaining"
    await session.save()
    logger.info("[CONCEPT_NOTES] dismissed advance_index=%s", new_idx)
    return {
        "type": "feedback",
        "message": "Perfect — let's explore the next key idea.",
        "correct": True,
        "current_concept": session.current_concept or "",
    }


async def handle_concept_notes_continue(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    """Dismiss notes popup and continue lesson flow."""
    if not is_concept_notes_mode(session):
        return {"type": "noop"}

    session.concept_notes_active = False
    session.concept_notes_concept = None
    session.concept_notes_markdown = None
    await session.save()
    return await _advance_after_concept_notes(
        ctx, session, session_id, student_id, topic
    )


def normalize_concept_question_action(
    session: Session,
    *,
    action: str | None,
    student_text: str,
) -> str | None:
    """Map legacy button ids and block skip during concept-question flow."""
    text = (student_text or "").strip()
    if action == "skip":
        return None
    if action == "ask_question":
        return "ask_another"
    if action == "understand":
        if bool(getattr(session, "concept_question_followup", False)) or bool(
            getattr(session, "concept_question_clarifying", False)
        ):
            return "concept_q_next"
        if text.lower().startswith("__action:"):
            return "concept_q_next"
        return None
    return action


def _keywords(text: str) -> set[str]:
    stop = {
        "that", "this", "with", "from", "they", "them", "what", "when", "where",
        "which", "about", "things", "thing", "living", "characteristics",
    }
    words = {w.lower() for w in _WORD_RE.findall(text or "")}
    return {w for w in words if w not in stop and len(w) >= 3}


def _reference_valid_items(reference: str) -> set[str]:
    items: set[str] = set()
    for part in re.split(r"[,;•\n]|(?:\band\b)", reference or "", flags=re.I):
        items |= _keywords(part)
    items |= _keywords(reference)
    return items


def _short_correct_feedback(
    student: str,
    db_answer: str,
    *,
    question: str = "",
    taught_ctx: dict[str, Any] | None = None,
) -> str:
    praise = random.choice(_PRAISE)
    return build_correct_answer_message(
        student,
        question,
        db_answer,
        taught_ctx or {},
        praise=praise,
    )


def _partial_answer_correct(
    student: str, reference: str, *, question: str = ""
) -> bool:
    """Any one valid reference item counts when the question asks for a single answer."""
    if answer_contradicts_lesson(student, question, reference):
        return False
    st = _keywords(student)
    valid = _reference_valid_items(reference)
    overlap = st & valid
    if not overlap:
        return False
    if not question_expects_single_item(question):
        return True
    # Single-item: must name exactly one valid characteristic, not a list.
    return len(overlap) == 1


def _keyword_overlap_correct(
    student: str, reference: str, *, question: str = ""
) -> bool:
    """Heuristic for list-style correct answers (grow, breathe, reproduce)."""
    if answer_contradicts_lesson(student, question, reference):
        return False
    ref_kw = _keywords(reference)
    st_kw = _keywords(student)
    if len(ref_kw) < 2 or len(st_kw) < 1:
        return False
    overlap = ref_kw & st_kw
    if len(overlap) >= min(2, len(ref_kw)):
        return True
    if len(ref_kw) >= 3 and len(overlap) / len(ref_kw) >= 0.6:
        return True
    return False


def _cap_sentences(text: str, max_sentences: int = 4) -> str:
    t = (text or "").strip()
    if not t:
        return t
    parts = re.split(r"(?<=[.!?])\s+", t)
    kept = [p for p in parts if p.strip()][:max_sentences]
    return " ".join(kept).strip()


async def _evaluate_concept_answer(
    concept: str,
    question: str,
    student: str,
    reference: str,
    *,
    taught_ctx: dict[str, Any] | None = None,
    question_type: str | None = None,
    mcq_options: list[str] | None = None,
) -> tuple[bool, int]:
    from app.services.handlers.concept_check_question_types import mcq_answer_matches

    options = list(mcq_options or [])
    is_mcq = question_type == "mcq" or len(options) >= 2

    if is_mcq and options:
        if mcq_answer_matches(student, reference, options):
            return True, TEACHBACK_PASS_THRESHOLD
        return False, 0

    partial = question_expects_single_item(question)
    taught_ctx = taught_ctx or {}

    if answer_contradicts_lesson(student, question, reference):
        return False, 0

    if is_step_count_question(question) and taught_content_supports_answer(
        question, student, taught_ctx
    ):
        return True, TEACHBACK_PASS_THRESHOLD

    if question_asks_about_process_step(question) and taught_content_supports_answer(
        question, student, taught_ctx
    ):
        return True, TEACHBACK_PASS_THRESHOLD

    taught_block = format_grading_context_block(taught_ctx)
    eval_ctx = (
        f"Question: {question}\nExpected answer: {reference}"
        if reference.strip()
        else taught_block or None
    )
    if taught_block:
        eval_ctx = (
            (eval_ctx or f"Question: {question}")
            + "\n\nAUTHORITATIVE LESSON CONTENT (grade ONLY against this — "
            "ignore generic curriculum if it conflicts):\n"
            + taught_block
        )
    if partial and reference.strip():
        eval_ctx += (
            "\n\nGRADING NOTE: The question asks for ONLY ONE item. "
            "Mark CORRECT if the student names any one valid item from the "
            "expected answer — they do NOT need to list every item. "
            "Mark WRONG if the answer contradicts the lesson (e.g. says something "
            "is NOT living when the lesson says it is), even if it mentions "
            "related words."
        )
    if is_step_count_question(question):
        n = effective_taught_item_count(taught_ctx)
        if n > 0:
            eval_ctx += (
                f"\n\nGRADING NOTE: This lesson taught exactly {n} steps on the board. "
                f"The numeric answer {n} is fully correct."
            )

    eval_result: dict = {}
    try:
        eval_result = await _engine_evaluate_answer(
            concept or question,
            student,
            reference_context=eval_ctx,
        )
    except Exception:  # noqa: BLE001
        eval_result = {"correct": False, "score": 40, "feedback": ""}

    score = int(eval_result.get("score", 0) or 0)
    correct = bool(eval_result.get("correct")) or score >= TEACHBACK_PASS_THRESHOLD
    if not correct and reference.strip():
        if partial and _partial_answer_correct(student, reference, question=question):
            correct = True
            score = max(score, TEACHBACK_PASS_THRESHOLD)
        elif not partial:
            correct = _keyword_overlap_correct(student, reference, question=question)
            if correct:
                score = max(score, TEACHBACK_PASS_THRESHOLD)
    return correct, score


async def arm_concept_questions_after_opening(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> None:
    """Arm question 1 after main VTSE opening."""
    session.concept_questions_active = True
    session.concept_question_index = 0
    session.concept_question_followup = False
    session.concept_question_clarifying = False
    session.concept_question_pending_advance = False
    session.concept_question_confusion_log = []
    session.concept_quiz_used_facts = []
    session.student_questions_active = False
    session.student_questions_concept = None
    session.current_step_in_concept = 0
    session.flow_state = "concept_questions"
    session.learning_state = "explaining"
    await _load_question_at_index(ctx, session, session_id, student_id, topic, 0)
    logger.info(
        "[CONCEPT_Q] armed concept=%s q_index=0 question_len=%s",
        getattr(session, "current_concept", ""),
        len((getattr(session, "current_question", None) or "")),
    )


async def _load_question_at_index(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    index: int,
) -> None:
    from app.services.handlers.concept_check_question_service import (
        apply_concept_check_pack_to_session,
        load_concept_check_question,
    )

    pack = await load_concept_check_question(
        ctx, session, session_id, student_id, topic, index
    )
    apply_concept_check_pack_to_session(session, pack, index)
    await session.save()


async def _explain_clarification_on_board(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    student_text: str,
) -> str:
    cc = (getattr(session, "current_concept", None) or "").strip() or "this concept"
    last_q = (getattr(session, "current_question", None) or "").strip()
    taught_ctx = await build_concept_quiz_taught_context(session_id, session)
    taught_block = format_grading_context_block(taught_ctx)
    rag_question = (
        f'The student is learning "{cc}". Question: "{last_q}".\n'
        f'Confusion: "{student_text.strip()}"\n\n'
    )
    if taught_block:
        rag_question += (
            "WHAT WAS TAUGHT ON THE BOARD (authoritative — use ONLY this):\n"
            f"{taught_block}\n\n"
        )
    rag_question += (
        "Reply in 2-3 short sentences only. Clarify this one point using ONLY "
        "the board lesson above. Do not invent facts, examples, or details that "
        "were not taught. No new lesson, no quiz question, no bullet lists."
    )
    rag_service, context, student_profile, topic_for_prompt = await _concept_check_board_rag_bundle(
        ctx,
        session,
        student_id,
        topic,
        taught_ctx=taught_ctx,
        session_id=session_id,
    )
    answer = await generate_tutor_rag_reply(
        session,
        session_id,
        student_id,
        rag_question,
        session.topic_id,
        "UNKNOWN",
        "explaining",
        topic_for_prompt,
        rag_service,
        context,
        student_profile,
        EventRepository(),
        persist_session_qa=False,
    )
    return _cap_sentences(
        coerce_plain_text_reply((answer or "").strip() or "Let me clarify that in simpler terms."),
        3,
    )


async def _generate_correct_feedback_on_board(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    student_text: str,
    reference: str,
    *,
    question: str = "",
    taught_ctx: dict[str, Any] | None = None,
) -> str:
    """LLM praise for a correct concept-check answer; falls back to template text."""
    cc = (getattr(session, "current_concept", None) or "").strip() or "this concept"
    last_q = (question or getattr(session, "current_question", None) or "").strip()
    taught_ctx = taught_ctx or await build_concept_quiz_taught_context(session_id, session)
    taught_block = format_grading_context_block(taught_ctx)
    clean_ref = clean_db_answer_for_display(reference)

    rag_question = (
        f'The student answered CORRECTLY.\n'
        f'Concept: "{cc}". Question: "{last_q}".\n'
        f'Student said: "{student_text.strip()}".\n\n'
    )
    if taught_block:
        rag_question += (
            "WHAT WAS TAUGHT ON THE BOARD (authoritative — use ONLY this):\n"
            f"{taught_block}\n\n"
        )
    if clean_ref:
        rag_question += f"Full correct idea for this question: {clean_ref}\n\n"

    rag_question += (
        "Write 2 short sentences (max 45 words) praising the student.\n"
        "Requirements:\n"
        "- Use fresh, natural wording — do NOT reuse stock phrases like "
        "'Good thinking — that's correct' or 'Exactly — you've got it'\n"
        "- Quote or paraphrase what the student said they got right\n"
        "- Connect their answer only to ideas from WHAT WAS TAUGHT ON THE BOARD "
        "(or the correct idea above) — do not add new facts\n"
        "- Warm tutor tone. Plain text only — no bullets, no markdown, no new question\n"
        "- Do not mention answer keys, grading, or scoring"
    )

    try:
        rag_service, context, student_profile, topic_for_prompt = await _concept_check_board_rag_bundle(
            ctx,
            session,
            student_id,
            topic,
            taught_ctx=taught_ctx,
            session_id=session_id,
        )
        answer = await generate_tutor_rag_reply(
            session,
            session_id,
            student_id,
            rag_question,
            session.topic_id,
            "UNKNOWN",
            "explaining",
            topic_for_prompt,
            rag_service,
            context,
            student_profile,
            EventRepository(),
            persist_session_qa=False,
        )
        msg = _cap_sentences(
            coerce_plain_text_reply((answer or "").strip()),
            3,
        )
        if len(msg.split()) >= 6:
            return msg
    except Exception:  # noqa: BLE001
        logger.exception("[CONCEPT_Q] correct_feedback LLM failed")

    return _short_correct_feedback(
        student_text,
        reference,
        question=last_q,
        taught_ctx=taught_ctx,
    )


async def _explain_wrong_answer_on_board(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    student_text: str,
    reference: str,
    *,
    question: str = "",
    taught_ctx: dict[str, Any] | None = None,
) -> str:
    cc = (getattr(session, "current_concept", None) or "").strip() or "this concept"
    last_q = (question or getattr(session, "current_question", None) or "").strip()
    taught_ctx = taught_ctx or await build_concept_quiz_taught_context(session_id, session)
    taught_block = format_grading_context_block(taught_ctx)

    rag_question = (
        f'Concept: "{cc}". Question: "{last_q}".\n'
        f'Student answered: "{student_text.strip()}".\n\n'
    )
    if taught_block:
        rag_question += (
            "WHAT WAS TAUGHT ON THE BOARD (authoritative — use ONLY this):\n"
            f"{taught_block}\n\n"
        )
    elif reference.strip():
        rag_question += f"Reference: {reference.strip()}\n\n"

    rag_question += (
        "In 2-3 short sentences, explain the correct idea for the whiteboard. "
        "Base your answer ONLY on what was taught in this lesson (board text above). "
        "Do not invent facts, examples, or details that were not taught. "
        "Be encouraging. No bullet lists. Do not ask a new question."
    )
    rag_service, context, student_profile, topic_for_prompt = await _concept_check_board_rag_bundle(
        ctx,
        session,
        student_id,
        topic,
        taught_ctx=taught_ctx,
        session_id=session_id,
    )
    answer = await generate_tutor_rag_reply(
        session,
        session_id,
        student_id,
        rag_question,
        session.topic_id,
        "UNKNOWN",
        "explaining",
        topic_for_prompt,
        rag_service,
        context,
        student_profile,
        EventRepository(),
        persist_session_qa=False,
    )
    return _cap_sentences(
        coerce_plain_text_reply(
            (answer or "").strip() or "Let's look at the correct idea together."
        ),
        4,
    )


def _followup_buttons(session: Session) -> list[dict[str, str]]:
    idx = int(getattr(session, "concept_question_index", 0) or 0)
    on_last = idx >= CONCEPT_QUESTIONS_PER_CONCEPT - 1
    next_label = "I understand" if on_last else "I understand — next question"
    return teacher_buttons(
        [
            ("ask_another", "I still have a confusion"),
            ("concept_q_next", next_label),
        ]
    )


async def complete_concept_and_advance(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    """Finish 3-question loop; show LLM notes before advancing to next concept."""
    cc = (getattr(session, "current_concept", None) or "").strip()
    session.concept_questions_active = False
    session.concept_question_followup = False
    session.concept_question_clarifying = False
    session.concept_question_pending_advance = False
    from app.services.handlers.concept_check_question_service import (
        clear_concept_check_question_fields,
    )

    clear_concept_check_question_fields(session)
    session.current_step_in_concept = 0
    session.current_concept_mastered = True
    session.student_questions_active = False

    markdown = await _generate_concept_notes_markdown(
        ctx, session, session_id, student_id, topic, concept=cc
    )
    history = list(getattr(session, "concept_notes_history", None) or [])
    history.append({"concept": cc, "markdown": markdown[:8000]})
    session.concept_notes_history = history[-20:]
    session.concept_notes_active = True
    session.concept_notes_concept = cc[:500] if cc else None
    session.concept_notes_markdown = markdown[:8000]
    session.concept_question_confusion_log = []
    session.flow_state = "explaining"
    session.learning_state = "explaining"
    await session.save()
    logger.info("[CONCEPT_NOTES] armed concept=%s len=%s", cc, len(markdown))
    return {
        "type": "concept_notes",
        "message": markdown,
        "concept_name": cc,
        "current_concept": cc,
    }


async def handle_concept_q_auto_advance(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    """Load the next question after the praise beat (frontend-triggered)."""
    if not bool(getattr(session, "concept_question_pending_advance", False)):
        return {"type": "noop"}

    session.concept_question_pending_advance = False
    idx = int(getattr(session, "concept_question_index", 0) or 0)
    if idx >= CONCEPT_QUESTIONS_PER_CONCEPT - 1:
        await session.save()
        return await complete_concept_and_advance(ctx, session, session_id, student_id, topic)

    next_index = idx + 1
    await _load_question_at_index(ctx, session, session_id, student_id, topic, next_index)
    session.flow_state = "concept_questions"
    await session.save()
    return {"type": "noop"}


async def handle_concept_q_next(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    session.concept_question_followup = False
    session.concept_question_clarifying = False
    idx = int(getattr(session, "concept_question_index", 0) or 0)
    if idx >= CONCEPT_QUESTIONS_PER_CONCEPT - 1:
        await session.save()
        return await complete_concept_and_advance(ctx, session, session_id, student_id, topic)

    next_index = idx + 1
    await _load_question_at_index(ctx, session, session_id, student_id, topic, next_index)
    session.flow_state = "concept_questions"
    await session.save()
    cc = session.current_concept or ""
    q = session.current_question or ""
    return {
        "type": "feedback",
        "message": f"Here's question {next_index + 1} of {CONCEPT_QUESTIONS_PER_CONCEPT}. Take your time.",
        "correct": True,
        "current_concept": cc,
        "question_preview": q,
    }


async def handle_concept_questions_dispatch(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    student_text: str = "",
    action: str | None = None,
) -> dict[str, Any]:
    """Route concept-question loop actions and free-text turns."""
    action = normalize_concept_question_action(
        session, action=action, student_text=student_text
    )
    cc = session.current_concept or ""

    if action == "concept_q_auto_advance":
        return await handle_concept_q_auto_advance(
            ctx, session, session_id, student_id, topic
        )

    if action == "concept_q_next":
        return await handle_concept_q_next(ctx, session, session_id, student_id, topic)

    if action == "ask_another":
        session.concept_question_clarifying = True
        session.concept_question_followup = False
        session.flow_state = "concept_questions"
        await session.save()
        return {
            "type": "question_prompt",
            "message": "What are you still confused about?",
            "current_concept": cc,
            "buttons": [],
        }

    if bool(getattr(session, "concept_question_clarifying", False)) and student_text.strip():
        _log_concept_confusion(session, f"Asked: {student_text.strip()}")
        msg = await _explain_clarification_on_board(
            ctx, session, session_id, student_id, topic, student_text
        )
        session.concept_question_clarifying = False
        session.concept_question_followup = True
        session.flow_state = "concept_questions"
        await session.save()
        return {
            "type": "explanation",
            "message": msg,
            "current_concept": cc,
            "buttons": _followup_buttons(session),
        }

    if bool(getattr(session, "concept_question_followup", False)):
        if student_text.strip() and not student_text.lower().startswith("__action:"):
            session.concept_question_clarifying = True
            session.concept_question_followup = False
            await session.save()
            return await handle_concept_questions_dispatch(
                ctx,
                session,
                session_id,
                student_id,
                topic,
                student_text=student_text,
                action=None,
            )
        return {
            "type": "question_prompt",
            "message": "Use the buttons when you're ready to continue.",
            "current_concept": cc,
            "buttons": _followup_buttons(session),
        }

    q_st = student_text.strip()
    if not q_st or q_st.lower().startswith("__action:"):
        return {
            "type": "question_prompt",
            "message": "Type or speak your answer when you're ready.",
            "current_concept": cc,
            "buttons": [],
        }

    last_q = (getattr(session, "current_question", None) or "").strip()
    db_raw = (getattr(session, "current_concept_question_answer", None) or "").strip()
    mcq_options = list(
        getattr(session, "current_concept_question_options", None) or []
    )
    question_type = getattr(session, "current_concept_question_type", None) or None
    if not question_type and len(mcq_options) >= 2:
        question_type = "mcq"
    cc_eval = (getattr(session, "current_concept", None) or "").strip() or last_q
    taught_ctx = await build_concept_quiz_taught_context(session_id, session)
    grading_ref = resolve_reference_for_question(last_q, db_raw, taught_ctx)
    answer_ref = db_raw if question_type == "mcq" else grading_ref

    correct, score = await _evaluate_concept_answer(
        cc_eval,
        last_q,
        q_st,
        answer_ref,
        taught_ctx=taught_ctx,
        question_type=question_type,
        mcq_options=mcq_options,
    )
    logger.info(
        "[CONCEPT_Q] evaluate correct=%s score=%s q_index=%s",
        correct,
        score,
        getattr(session, "concept_question_index", 0),
    )

    if correct:
        praise = await _generate_correct_feedback_on_board(
            ctx,
            session,
            session_id,
            student_id,
            topic,
            q_st,
            grading_ref,
            question=last_q,
            taught_ctx=taught_ctx,
        )
        session.concept_question_pending_advance = True
        session.concept_question_followup = False
        session.concept_question_clarifying = False
        session.flow_state = "concept_questions"
        await session.save()
        return {
            "type": "explanation",
            "message": praise,
            "current_concept": cc,
            "buttons": [],
        }

    board_msg = await _explain_wrong_answer_on_board(
        ctx, session, session_id, student_id, topic, q_st, db_raw,
        question=last_q, taught_ctx=taught_ctx,
    )
    _log_concept_confusion(
        session,
        f'On "{last_q[:120]}": answered "{q_st[:120]}"',
    )
    session.concept_question_followup = True
    session.concept_question_clarifying = False
    session.flow_state = "concept_questions"
    await session.save()
    return {
        "type": "explanation",
        "message": board_msg,
        "current_concept": cc,
        "buttons": _followup_buttons(session),
    }
