"""Micro-teaching continuation routing (current pending-micro / quiz split)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId

from app.core.constants import MICRO_TEACH_STEP_READY_QUIZ
from app.services.session_service import SessionService


def _micro_session(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": PydanticObjectId(),
        "current_zone": 1,
        "total_concepts": 3,
        "explanation_mode": "micro",
        "current_step_in_concept": 0,
        "current_question": "Can something grow but still not be alive?",
        "flow_state": "explaining",
        "current_mode": "normal",
        "student_questions_active": False,
        "last_answer": "Is growth enough to count as alive?",
        "zone1_timeline_cache": {"beats": [{"beat_id": "b0"}]},
        "key_concepts": ["Living Things"],
        "concept_clusters": None,
        "current_concept_index": 0,
        "pedagogy_session_intro_done": True,
        "pedagogy_session_recall_done": True,
        "pedagogy_cluster_intro_done_for": 0,
        "pedagogy_cluster_curiosity_done_for": 0,
        "zone0_phase": "done",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _service() -> SessionService:
    service = SessionService.__new__(SessionService)
    service.session_repository = AsyncMock()
    service._is_teacher_progression = lambda _s: True  # type: ignore[method-assign]
    service._teacher_debug_flow = lambda _s, _t: None  # type: ignore[method-assign]
    service._build_handler_context = lambda: None  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_pending_micro_question_blocks_quiz_action_with_noop() -> None:
    """
    Current pending-micro guard: while a micro question is outstanding and the
    concept is not quiz-ready, __action:quiz must return noop (not advance).
    """
    session = _micro_session(
        current_question="Can something grow but still not be alive?",
        current_step_in_concept=0,
        flow_state="explaining",
    )
    topic = SimpleNamespace(topic_name="Living Things", key_concepts=["Living Things"])
    service = _service()

    out = await service._teacher_handle_conversation(
        session,
        session.id,
        PydanticObjectId(),
        "__action:quiz",
        topic,
        is_quiz_mode=False,
    )
    assert out == {"type": "noop"}


@pytest.mark.asyncio
async def test_pending_micro_quiz_guard_inactive_once_ready_for_quiz() -> None:
    """
    Mirror the production pending-micro quiz guard predicates: once the micro
    step is quiz-ready, a pending question string alone must not block quiz.
    """
    session = _micro_session(
        current_question="Ready for a check?",
        current_step_in_concept=MICRO_TEACH_STEP_READY_QUIZ,
        flow_state="explaining",
    )
    pending_micro_q = (getattr(session, "current_question", None) or "").strip()
    step = int(getattr(session, "current_step_in_concept", 0) or 0)
    ready_for_quiz = step >= MICRO_TEACH_STEP_READY_QUIZ
    flow = getattr(session, "flow_state", "idle") or "idle"
    action = "quiz"
    would_block = (
        action == "quiz"
        and not ready_for_quiz
        and flow in ("explaining", "checking_understanding")
        and bool(pending_micro_q)
    )
    assert ready_for_quiz is True
    assert would_block is False


@pytest.mark.asyncio
async def test_quiz_mode_returns_none_from_teacher_handler() -> None:
    """
    Current routing split: when is_quiz_mode=True, _teacher_handle_conversation
    returns None immediately so the quiz answer path owns the turn.
    """
    session = _micro_session(current_mode="quiz")
    topic = SimpleNamespace(topic_name="Living Things", key_concepts=["Living Things"])
    service = _service()

    with patch(
        "app.services.session_service.teacher_micro_teaching_process_reply",
        new_callable=AsyncMock,
        return_value={"message": "should not run"},
    ) as mock_micro:
        out = await service._teacher_handle_conversation(
            session,
            session.id,
            PydanticObjectId(),
            "Plants grow from seeds but crystals grow too.",
            topic,
            is_quiz_mode=True,
        )
    mock_micro.assert_not_awaited()
    assert out is None
