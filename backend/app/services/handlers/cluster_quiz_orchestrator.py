"""
Zone 1 cluster-end quiz — structured 3-question loop (2 descriptive + 1 MCQ).

Mirrors concept-check orchestration: praise on correct, explain + confusion loop on wrong.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from beanie.odm.fields import PydanticObjectId

from app.core.constants import CLUSTER_QUESTIONS_PER_CLUSTER
from app.services.handlers.cluster_check_question_service import (
    apply_cluster_check_pack_to_session,
    clear_cluster_check_question_fields,
    cluster_concepts_for_session,
    load_cluster_check_question,
)
from app.services.handlers.teaching_transcript_service import (
    build_cluster_quiz_taught_context,
)
from app.services.handlers.cluster_utils import resolve_clusters
from app.services.handlers.concept_question_orchestrator import (
    _evaluate_concept_answer,
    _explain_clarification_on_board,
    _explain_wrong_answer_on_board,
    _generate_correct_feedback_on_board,
)
from app.services.handlers.concept_taught_context import (
    resolve_reference_for_question,
)
from app.services.handlers.explanation_handler import teacher_buttons

if TYPE_CHECKING:
    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)


def is_cluster_quiz_mode(session: Session) -> bool:
    return bool(getattr(session, "cluster_quiz_active", False))


def _log_cluster_confusion(session: Session, entry: str) -> None:
    text = (entry or "").strip()
    if not text:
        return
    log = list(getattr(session, "cluster_quiz_confusion_log", None) or [])
    log.append(text[:500])
    session.cluster_quiz_confusion_log = log[-12:]


def normalize_cluster_quiz_action(
    session: Session,
    *,
    action: str | None,
    student_text: str,
) -> str | None:
    text = (student_text or "").strip()
    if action == "skip":
        return None
    if action == "ask_question":
        return "ask_another"
    if action == "understand":
        if bool(getattr(session, "cluster_quiz_followup", False)) or bool(
            getattr(session, "cluster_quiz_clarifying", False)
        ):
            return "cluster_q_next"
        if text.lower().startswith("__action:"):
            return "cluster_q_next"
        return None
    return action


def _cluster_followup_buttons(session: Session) -> list[dict[str, str]]:
    idx = int(getattr(session, "cluster_quiz_index", 0) or 0)
    on_last = idx >= CLUSTER_QUESTIONS_PER_CLUSTER - 1
    next_label = "I understand" if on_last else "I understand — next question"
    return teacher_buttons(
        [
            ("ask_another", "I still have a confusion"),
            ("cluster_q_next", next_label),
        ]
    )


async def _load_question_at_index(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    index: int,
) -> None:
    pack = await load_cluster_check_question(
        ctx, session, session_id, student_id, topic, index
    )
    apply_cluster_check_pack_to_session(session, pack, index)
    await session.save()


async def arm_cluster_quiz(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> None:
    """Arm question 1 at cluster boundary."""
    session.cluster_quiz_active = True
    session.cluster_quiz_index = 0
    session.cluster_quiz_followup = False
    session.cluster_quiz_clarifying = False
    session.cluster_quiz_pending_advance = False
    session.cluster_quiz_confusion_log = []
    session.cluster_quiz_used_facts = []
    session.cluster_quiz_questions = []
    session.current_mode = "normal"
    session.flow_state = "cluster_quiz"
    session.learning_state = "quizzing"
    await _load_question_at_index(ctx, session, session_id, student_id, topic, 0)
    logger.info(
        "[CLUSTER_Q] armed q_index=0 question_len=%s",
        len((getattr(session, "current_question", None) or "")),
    )


async def complete_cluster_quiz_and_advance(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    """Finish cluster quiz and start cluster teachback with a grounded long question."""
    from app.services.handlers.cluster_teachback_service import (
        generate_cluster_teachback_question,
    )

    kc = [
        str(c).strip()
        for c in (getattr(session, "key_concepts", None) or [])
        if str(c).strip()
    ]
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    cidx = int(getattr(session, "current_cluster_index", 0) or 0)
    cluster_concepts = list(clusters[cidx]) if 0 <= cidx < len(clusters) else []

    session.cluster_quiz_active = False
    session.cluster_quiz_questions = []
    session.cluster_quiz_index = 0
    session.cluster_quiz_followup = False
    session.cluster_quiz_clarifying = False
    session.cluster_quiz_pending_advance = False
    clear_cluster_check_question_fields(session)
    session.cluster_quiz_confusion_log = []
    session.current_mode = "teachback"
    session.flow_state = "teachback"
    session.teachback_concepts = [
        str(c).strip() for c in cluster_concepts if str(c).strip()
    ]
    session.teachback_attempts = 0
    session.asked_missing_concepts = []
    session.sus_reinforcement_done = False
    session.clarity_sus_retry_done = False
    session.learning_state = "teachback"

    teachback_q = await generate_cluster_teachback_question(
        ctx,
        session,
        session_id,
        topic,
        concepts=session.teachback_concepts,
    )
    session.cluster_teachback_question = teachback_q[:8000]
    session.cluster_teachback_active = True
    session.cluster_teachback_phase = "main"
    session.cluster_teachback_socratic_turn = 0
    session.cluster_teachback_last_score = None
    session.current_question = teachback_q[:5000]
    await session.save()
    logger.info(
        "[CLUSTER_Q] complete → cluster teachback concepts=%s q_len=%s",
        cluster_concepts,
        len(teachback_q),
    )
    return {
        "type": "feedback",
        "message": (
            "Great work on the cluster quiz! Open teachback on the whiteboard "
            "and answer the question in your own words."
        ),
        "correct": True,
        "current_concept": getattr(session, "current_concept", None) or "",
    }


async def handle_cluster_q_auto_advance(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    if not bool(getattr(session, "cluster_quiz_pending_advance", False)):
        return {"type": "noop"}

    session.cluster_quiz_pending_advance = False
    idx = int(getattr(session, "cluster_quiz_index", 0) or 0)
    if idx >= CLUSTER_QUESTIONS_PER_CLUSTER - 1:
        await session.save()
        return await complete_cluster_quiz_and_advance(
            ctx, session, session_id, student_id, topic
        )

    next_index = idx + 1
    await _load_question_at_index(
        ctx, session, session_id, student_id, topic, next_index
    )
    session.flow_state = "cluster_quiz"
    await session.save()
    return {"type": "noop"}


async def handle_cluster_q_next(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
) -> dict[str, Any]:
    session.cluster_quiz_followup = False
    session.cluster_quiz_clarifying = False
    idx = int(getattr(session, "cluster_quiz_index", 0) or 0)
    if idx >= CLUSTER_QUESTIONS_PER_CLUSTER - 1:
        await session.save()
        return await complete_cluster_quiz_and_advance(
            ctx, session, session_id, student_id, topic
        )

    next_index = idx + 1
    await _load_question_at_index(
        ctx, session, session_id, student_id, topic, next_index
    )
    session.flow_state = "cluster_quiz"
    await session.save()
    cc = session.current_concept or ""
    q = session.current_question or ""
    return {
        "type": "feedback",
        "message": f"Here's question {next_index + 1} of {CLUSTER_QUESTIONS_PER_CLUSTER}. Take your time.",
        "correct": True,
        "current_concept": cc,
        "question_preview": q,
    }


async def handle_cluster_quiz_dispatch(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    student_text: str = "",
    action: str | None = None,
) -> dict[str, Any]:
    action = normalize_cluster_quiz_action(
        session, action=action, student_text=student_text
    )
    cc = session.current_concept or ""

    if action == "cluster_q_auto_advance":
        return await handle_cluster_q_auto_advance(
            ctx, session, session_id, student_id, topic
        )

    if action == "cluster_q_next":
        return await handle_cluster_q_next(
            ctx, session, session_id, student_id, topic
        )

    if action == "ask_another":
        session.cluster_quiz_clarifying = True
        session.cluster_quiz_followup = False
        session.flow_state = "cluster_quiz"
        await session.save()
        return {
            "type": "question_prompt",
            "message": "What are you still confused about?",
            "current_concept": cc,
            "buttons": [],
        }

    if bool(getattr(session, "cluster_quiz_clarifying", False)) and student_text.strip():
        _log_cluster_confusion(session, f"Asked: {student_text.strip()}")
        msg = await _explain_clarification_on_board(
            ctx, session, session_id, student_id, topic, student_text
        )
        session.cluster_quiz_clarifying = False
        session.cluster_quiz_followup = True
        session.flow_state = "cluster_quiz"
        await session.save()
        return {
            "type": "explanation",
            "message": msg,
            "current_concept": cc,
            "buttons": _cluster_followup_buttons(session),
        }

    if bool(getattr(session, "cluster_quiz_followup", False)):
        if student_text.strip() and not student_text.lower().startswith("__action:"):
            session.cluster_quiz_clarifying = True
            session.cluster_quiz_followup = False
            await session.save()
            return await handle_cluster_quiz_dispatch(
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
            "buttons": _cluster_followup_buttons(session),
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
    db_raw = (getattr(session, "cluster_quiz_question_answer", None) or "").strip()
    mcq_options = list(
        getattr(session, "cluster_quiz_question_options", None) or []
    )
    question_type = getattr(session, "cluster_quiz_question_type", None) or None
    if not question_type and len(mcq_options) >= 2:
        question_type = "mcq"
    concepts = cluster_concepts_for_session(session)
    eval_concept = ", ".join(concepts[:3]) if concepts else last_q
    taught_ctx = await build_cluster_quiz_taught_context(session_id, session)
    grading_ref = resolve_reference_for_question(last_q, db_raw, taught_ctx)
    answer_ref = db_raw if question_type == "mcq" else grading_ref

    correct, score = await _evaluate_concept_answer(
        eval_concept,
        last_q,
        q_st,
        answer_ref,
        taught_ctx=taught_ctx,
        question_type=question_type,
        mcq_options=mcq_options,
    )
    logger.info(
        "[CLUSTER_Q] evaluate correct=%s score=%s q_index=%s",
        correct,
        score,
        getattr(session, "cluster_quiz_index", 0),
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
        session.cluster_quiz_pending_advance = True
        session.cluster_quiz_followup = False
        session.cluster_quiz_clarifying = False
        session.flow_state = "cluster_quiz"
        await session.save()
        return {
            "type": "explanation",
            "message": praise,
            "current_concept": cc,
            "buttons": [],
        }

    board_msg = await _explain_wrong_answer_on_board(
        ctx,
        session,
        session_id,
        student_id,
        topic,
        q_st,
        db_raw,
        question=last_q,
        taught_ctx=taught_ctx,
    )
    _log_cluster_confusion(
        session,
        f'On "{last_q[:120]}": answered "{q_st[:120]}"',
    )
    session.cluster_quiz_followup = True
    session.cluster_quiz_clarifying = False
    session.flow_state = "cluster_quiz"
    await session.save()
    return {
        "type": "explanation",
        "message": board_msg,
        "current_concept": cc,
        "buttons": _cluster_followup_buttons(session),
    }
