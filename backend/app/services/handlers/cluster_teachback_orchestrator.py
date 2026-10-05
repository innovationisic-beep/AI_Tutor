"""
Cluster teachback orchestration — tiered LLM scoring and tutor responses.

>=80%  appreciate + restate correct answer → advance
50–79% Socratic probes (2) → simple ideal-answer explanation → advance
<50%   empathetic intro + simplified VTSE re-teach → new teachback question → retry
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from beanie.odm.fields import PydanticObjectId

from app.core.config import Settings
from app.core.constants import (
    CLUSTER_TEACHBACK_SOCRATIC_QUESTIONS,
    CLUSTER_TEACHBACK_SUS_EXCELLENT_DELTA,
    CLUSTER_TEACHBACK_SUS_PARTIAL_DELTA,
    CLUSTER_TEACHBACK_SUS_WEAK_DELTA,
    CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD,
)
from app.models.learning.teachback_evaluations import TeachbackEvaluation
from app.services.handlers.cluster_teachback_service import (
    cluster_teachback_tier,
    evaluate_cluster_teachback_answer,
    format_excellent_teachback_message,
    format_partial_start_message,
    format_post_socratic_explanation_message,
    format_socratic_followup_message,
    format_weak_teachback_intro,
    generate_cluster_socratic_question,
    generate_cluster_teachback_question,
    generate_cluster_teachback_simple_ideal_explanation,
)
from app.services.handlers.cluster_utils import (
    sync_current_cluster_index,
)
from app.services.handlers.teachback_handler import (
    _refine_sus_score,
    _update_sus_learning_signals,
)
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator

if TYPE_CHECKING:
    from app.models.learning.sessions import Session
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)


def _with_cluster_tb_board(payload: dict[str, Any]) -> dict[str, Any]:
    """Mark tutor prose that belongs on the whiteboard during cluster teachback."""
    return {**payload, "cluster_teachback_board": True}


def _clear_cluster_teachback_fields(session: Session) -> None:
    session.cluster_teachback_active = False
    session.cluster_teachback_question = None
    session.cluster_teachback_phase = "main"
    session.cluster_teachback_socratic_turn = 0
    session.cluster_teachback_last_score = None
    session.teachback_concepts = []
    session.asked_missing_concepts = []
    session.current_question = None


async def _record_cluster_teachback_evaluation(
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    *,
    question: str,
    student_answer: str,
    eval_res: dict[str, Any],
) -> None:
    score = float(eval_res.get("score", 0) or 0)
    await TeachbackEvaluation(
        organization_id=session.organization_id,
        student_id=student_id,
        session_id=session_id,
        topic_id=session.topic_id,
        question_text=question[:4000],
        student_response=student_answer[:8000],
        is_correct=score >= CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD,
        evaluation_score=score,
        feedback=str(eval_res.get("feedback") or "")[:4000],
        model_used=Settings.DEEPSEEK_MODEL,
        timestamp=datetime.utcnow(),
    ).insert()


async def _complete_cluster_teachback_pass(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Any,
    *,
    message: str,
) -> dict[str, Any]:
    """Advance past cluster teachback — zone transition gate or next concept."""
    from app.services.handlers.teachback_handler import (
        _get_current_concept,
        _refine_sus_score,
        _session_concept_sequence,
        _teacher_debug_flow,
        _update_sus_learning_signals,
    )

    kc = _session_concept_sequence(session, topic)
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    session.current_concept_index = idx + 1
    from app.services.session_concept_tracking import sync_session_concept_fields

    sync_session_concept_fields(session)
    session.current_cluster_index = sync_current_cluster_index(
        key_concepts=kc,
        concept_clusters=getattr(session, "concept_clusters", None),
        current_concept_index=int(session.current_concept_index or 0),
    )
    new_idx = int(session.current_concept_index or 0)
    tid = int(getattr(session, "total_concepts", 0) or 0)
    topic_done = tid > 0 and new_idx >= tid

    session.current_step_in_concept = 0
    session.teachback_attempts = 0
    session.sus_reinforcement_done = False
    session.clarity_sus_retry_done = False
    session.cluster_quiz_active = False
    session.cluster_quiz_questions = []
    session.cluster_quiz_index = 0
    _clear_cluster_teachback_fields(session)

    if topic_done:
        session.cluster_check_pending = False
        session.cluster_check_concepts = None
        session.retrieval_active = False
        session.retrieval_concept = None
        session.cluster_taught_points = []
        session.current_concept = None
        coordinator = ZoneTransitionCoordinator()
        payload = await coordinator.resolve_after_teachback_slice(
            session,
            topic_done=True,
            default_complete_message=(
                message
                or "Excellent — you've worked through this session! Really well done. 🌟"
            ),
            defer_gate_start=True,
        )
        if payload.get("type") == "_defer_gate":
            await session.save()
            _teacher_debug_flow(session, topic)
            return _with_cluster_tb_board(
                {
                    "type": "teachback_passed",
                    "message": message
                    or "Excellent — you've worked through this session! Really well done. 🌟",
                    "zone_transition_gate_pending": True,
                }
            )
        if payload.get("type") != "_continue":
            await session.save()
            _teacher_debug_flow(session, topic)
            return _with_cluster_tb_board(payload)
        session.flow_state = "completed"
        session.current_mode = "normal"
        session.learning_state = "explaining"
        session.clarity_gate_active = False
        session.clarity_gate_step = None
        session.clarity_gate_concepts = None
        await session.save()
        _teacher_debug_flow(session, topic)
        return _with_cluster_tb_board(
            {
                "type": "completed",
                "message": message
                or "Excellent — you've worked through this session! Really well done. 🌟",
            }
        )

    coordinator = ZoneTransitionCoordinator()
    mid_payload = await coordinator.resolve_after_teachback_slice(
        session,
        topic_done=False,
        default_complete_message="",
        defer_gate_start=True,
    )
    if mid_payload.get("type") == "_defer_gate":
        await session.save()
        _teacher_debug_flow(session, topic)
        return _with_cluster_tb_board(
            {
                "type": "teachback_passed",
                "message": message
                or "That connects well — nice work!",
                "zone_transition_gate_pending": True,
            }
        )
    if mid_payload.get("type") != "_continue":
        await session.save()
        _teacher_debug_flow(session, topic)
        return _with_cluster_tb_board(mid_payload)

    session.current_concept = _get_current_concept(session, topic)
    session.current_mode = "normal"
    session.flow_state = "idle"
    session.learning_state = "explaining"
    session.cluster_taught_points = []
    await session.save()
    weak_hint = ""
    if getattr(session, "recent_weak_concepts", None):
        weak_hint = (
            f" Keep in mind how {session.recent_weak_concepts[-1]} connects "
            "as we move forward."
        )
    _teacher_debug_flow(session, topic)
    return _with_cluster_tb_board(
        {
            "type": "teachback_passed",
            "message": (message or "That connects well — nice work!") + weak_hint,
            "current_concept": getattr(session, "current_concept", None) or "",
        }
    )


async def _run_simplified_vtse_reteach(
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Any,
    *,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
    missing_points: list[str],
) -> dict[str, Any] | str:
    """
    Full VTSE re-teach with simpler wording (weak-score path only).

    Same beat/visual structure as the original lesson; narration rewritten
    in easier language. Returns the explain-turn payload when available.
    """
    from app.services.handlers.cluster_teachback_service import (
        build_cluster_whiteboard_explanation,
    )

    taught_summary = await build_cluster_whiteboard_explanation(
        session, session_id, missing_points=missing_points or None
    )
    concepts = [
        str(c).strip()
        for c in (getattr(session, "teachback_concepts", None) or [])
        if str(c).strip()
    ]
    cluster_label = ", ".join(concepts[:6]) if concepts else "this cluster"
    prompt = (
        f"The student is confused about cluster '{cluster_label}' after teachback.\n"
        f"Re-teach this cluster on the whiteboard using FULL VTSE.\n\n"
        f"AUTHORITATIVE LESSON CONTENT:\n{taught_summary}\n\n"
        "REQUIREMENTS:\n"
        "- Keep the SAME beat structure, visual layout, and hierarchy as the "
        "original first teaching (same nodes/traits/steps — do not invent new topics)\n"
        "- Rewrite EVERY narration and annotation in MUCH SIMPLER, friendlier "
        "wording (short sentences, everyday words, gentle tone)\n"
        "- Do NOT copy the exact same sentences from the first lesson — paraphrase "
        "more simply so a struggling student can follow\n"
        "- Cover each taught characteristic clearly\n"
        "- Speak warmly and encouragingly — they found this hard\n"
        "- Do NOT ask a teachback question — the system will do that next\n"
    )
    fallback = taught_summary
    if topic is None:
        return fallback
    try:
        body = await teacher_explain_turn_fn(
            session,
            session_id,
            student_id,
            topic,
            prompt,
            intent="EXPLAIN",
            state_at_entry="explaining",
            next_flow_state="teachback",
            next_learning_state="teachback",
        )
        if isinstance(body, dict):
            if not str(body.get("message") or "").strip():
                body = {**body, "message": fallback}
            return body
        text = str(body or "").strip() or fallback
        return text
    except Exception:
        logger.exception("[CLUSTER_TEACHBACK] simplified VTSE re-teach failed")
        return fallback


def _update_cluster_teachback_sus(
    session: Session,
    *,
    tier: str,
    score: float,
    missing_points: list[str],
) -> None:
    passed = tier == "excellent"
    sus_now = float(getattr(session, "sus_score", 50.0) or 50.0)
    if passed:
        session.sus_score = min(100.0, sus_now + CLUSTER_TEACHBACK_SUS_EXCELLENT_DELTA)
    elif tier == "partial":
        session.sus_score = max(
            0.0, min(100.0, sus_now + CLUSTER_TEACHBACK_SUS_PARTIAL_DELTA)
        )
    else:
        session.sus_score = max(0.0, sus_now + CLUSTER_TEACHBACK_SUS_WEAK_DELTA)
    _update_sus_learning_signals(
        session,
        correct=passed,
        evaluation_score=score,
        missing_points=missing_points,
    )
    session.sus_score = _refine_sus_score(
        session,
        current_sus=float(getattr(session, "sus_score", 50.0) or 50.0),
    )


def _with_cluster_tb_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """Score / guidance that belongs in the teachback side panel (not whiteboard)."""
    return {**payload, "cluster_teachback_panel": True}


async def handle_cluster_teachback_reteach(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Any,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    """Run simplified VTSE after weak-score panel intro (frontend-triggered)."""
    phase = str(getattr(session, "cluster_teachback_phase", "main") or "main")
    if phase != "reteach_pending":
        return {"type": "noop"}

    cluster_concepts = [
        str(c).strip()
        for c in (getattr(session, "teachback_concepts", None) or [])
        if str(c).strip()
    ]
    if not cluster_concepts:
        return {"type": "noop"}

    # New VTSE attempt on the same concept must not inherit the previous
    # checkpoint, opening claim, or await flag.
    from app.services.pedagogy import vtse_opening_claim

    session.flow_checkpoint_pending = False
    session.flow_checkpoint_resolved = True
    session.concept_teaching_await_vtse_done = False
    session.zone1_last_completed_beat_index = None
    vtse_opening_claim.reset_vtse_opening(session)
    logger.info(
        "[VTSE_STAGE] reteach_attempt_reset session_id=%s concept_index=%s",
        session_id,
        getattr(session, "current_concept_index", None),
    )

    missing = [
        str(m).strip()
        for m in (getattr(session, "asked_missing_concepts", None) or [])
        if str(m).strip()
    ]
    vtse_result = await _run_simplified_vtse_reteach(
        session,
        session_id,
        student_id,
        topic,
        teacher_explain_turn_fn=teacher_explain_turn_fn,
        missing_points=missing or cluster_concepts,
    )
    new_q = await generate_cluster_teachback_question(
        ctx,
        session,
        session_id,
        topic,
        concepts=cluster_concepts,
    )
    session.cluster_teachback_question = new_q[:8000]
    session.current_question = new_q[:5000]
    session.cluster_teachback_phase = "main"
    session.cluster_teachback_socratic_turn = 0
    session.cluster_teachback_active = True
    session.current_mode = "teachback"
    session.flow_state = "teachback"
    session.learning_state = "teachback"
    await session.save()

    cc = getattr(session, "current_concept", None) or ""
    board_lead = "Let's go through this cluster again, step by step."

    if isinstance(vtse_result, dict) and isinstance(
        vtse_result.get("instruction_timeline_v3"), dict
    ):
        return _with_cluster_tb_board(
            {
                "type": "explanation",
                "message": board_lead,
                "current_concept": cc,
                "instruction_timeline_v3": vtse_result.get("instruction_timeline_v3"),
                "planner_source": vtse_result.get("planner_source"),
                "timeline_metadata": vtse_result.get("timeline_metadata"),
                "visual": vtse_result.get("visual"),
            }
        )

    reteach_text = (
        str(vtse_result.get("message") or "").strip()
        if isinstance(vtse_result, dict)
        else str(vtse_result or "").strip()
    )
    body = reteach_text or board_lead
    return _with_cluster_tb_board(
        {
            "type": "explanation",
            "message": body,
            "current_concept": cc,
        }
    )


async def handle_cluster_teachback_input(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic: Any,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    """Tiered cluster teachback — called from teachback_handler."""
    raw_action = (user_input or "").strip()
    if raw_action.lower().startswith("__action:flow_checkpoint_"):
        from app.services.handlers.flow_checkpoint_handler import (
            maybe_dispatch_flow_checkpoint,
        )

        dispatched = await maybe_dispatch_flow_checkpoint(
            ctx,
            session,
            session_id,
            student_id,
            topic,
            raw_action,
        )
        if dispatched is not None:
            return dispatched
        return {"type": "noop"}

    cluster_concepts = [
        str(c).strip()
        for c in (getattr(session, "teachback_concepts", None) or [])
        if str(c).strip()
    ]
    if not cluster_concepts:
        return {"type": "noop"}

    tb_question = (
        str(getattr(session, "cluster_teachback_question", None) or "").strip()
        or str(getattr(session, "current_question", None) or "").strip()
    )
    phase = str(getattr(session, "cluster_teachback_phase", "main") or "main")

    if phase == "socratic":
        return await _handle_cluster_teachback_socratic_turn(
            ctx,
            session,
            session_id,
            student_id,
            user_input,
            topic,
            teacher_explain_turn_fn,
            cluster_concepts=cluster_concepts,
            tb_question=tb_question,
        )

    eval_res = await evaluate_cluster_teachback_answer(
        session,
        session_id,
        student_answer=user_input,
        question=tb_question,
        concepts=cluster_concepts,
    )
    score = float(eval_res.get("score", 0) or 0)
    missing = [
        str(m).strip()
        for m in (eval_res.get("missing_points") or [])
        if str(m).strip()
    ]
    tier = cluster_teachback_tier(score)
    session.cluster_teachback_last_score = score
    session.recent_weak_concepts = list(
        dict.fromkeys(
            list(getattr(session, "recent_weak_concepts", None) or []) + missing
        )
    )[-3:]

    _update_cluster_teachback_sus(
        session, tier=tier, score=score, missing_points=missing
    )
    await _record_cluster_teachback_evaluation(
        session,
        session_id,
        student_id,
        question=tb_question,
        student_answer=user_input,
        eval_res=eval_res,
    )

    if tier == "excellent":
        message = format_excellent_teachback_message(eval_res)
        return await _complete_cluster_teachback_pass(
            ctx, session, session_id, topic, message=message
        )

    if tier == "partial":
        socratic_q = await generate_cluster_socratic_question(
            ctx,
            session,
            session_id,
            topic,
            concepts=cluster_concepts,
            missing_points=missing or cluster_concepts,
            prior_answer=user_input,
            turn_index=0,
        )
        session.cluster_teachback_phase = "socratic"
        session.cluster_teachback_socratic_turn = 0
        session.asked_missing_concepts = list(
            dict.fromkeys(missing)
        )[-6:]
        await session.save()
        return _with_cluster_tb_board(
            {
                "type": "teachback_retry",
                "message": format_partial_start_message(eval_res, socratic_q),
                "current_concept": getattr(session, "current_concept", None) or "",
                "score": score,
            }
        )

    return await _handle_cluster_teachback_weak_turn(
        ctx,
        session,
        session_id,
        student_id,
        user_input,
        topic,
        teacher_explain_turn_fn,
        cluster_concepts=cluster_concepts,
        eval_res=eval_res,
        missing=missing,
    )


async def _handle_cluster_teachback_socratic_turn(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic: Any,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
    *,
    cluster_concepts: list[str],
    tb_question: str,
) -> dict[str, Any]:
    """After partial score: 2 Socratic probes, then simple ideal answer → pass."""
    turn = int(getattr(session, "cluster_teachback_socratic_turn", 0) or 0) + 1
    session.cluster_teachback_socratic_turn = turn
    missing = [
        str(m).strip()
        for m in (getattr(session, "asked_missing_concepts", None) or [])
        if str(m).strip()
    ]

    if turn < CLUSTER_TEACHBACK_SOCRATIC_QUESTIONS:
        socratic_q = await generate_cluster_socratic_question(
            ctx,
            session,
            session_id,
            topic,
            concepts=cluster_concepts,
            missing_points=missing or cluster_concepts,
            prior_answer=user_input,
            turn_index=turn,
        )
        await session.save()
        return _with_cluster_tb_board(
            {
                "type": "teachback_retry",
                "message": format_socratic_followup_message(socratic_q),
                "current_concept": getattr(session, "current_concept", None) or "",
            }
        )

    simple_ideal = await generate_cluster_teachback_simple_ideal_explanation(
        session,
        session_id,
        question=tb_question,
        concepts=cluster_concepts,
        missing_points=missing,
    )
    message = format_post_socratic_explanation_message(simple_ideal)
    session.cluster_teachback_phase = "main"
    session.cluster_teachback_socratic_turn = 0
    return await _complete_cluster_teachback_pass(
        ctx, session, session_id, topic, message=message
    )


async def _handle_cluster_teachback_weak_turn(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic: Any,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
    *,
    cluster_concepts: list[str],
    eval_res: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    """Score <50: empathetic intro in panel → VTSE re-teach → new teachback question."""
    attempts = int(getattr(session, "teachback_attempts", 0) or 0) + 1
    session.teachback_attempts = attempts
    if attempts >= 2:
        session.teacher_flag = True

    session.asked_missing_concepts = list(dict.fromkeys(missing))[-6:]
    session.cluster_teachback_phase = "reteach_pending"
    session.cluster_teachback_active = True
    session.current_mode = "teachback"
    session.flow_state = "teachback"
    session.learning_state = "teachback"
    await session.save()

    cc = getattr(session, "current_concept", None) or ""
    return _with_cluster_tb_panel(
        {
            "type": "teachback_retry",
            "message": format_weak_teachback_intro(eval_res),
            "current_concept": cc,
            "score": eval_res.get("score"),
        }
    )
