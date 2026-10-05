"""
VTSE mid-timeline student question must PAUSE and RESUME, not complete the stage.

Run: pytest backend/tests/test_vtse_question_interrupt_resume.py -q
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.session_service import SessionService


def _vtse_await_session(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": PydanticObjectId(),
        "organization_id": PydanticObjectId(),
        "student_id": PydanticObjectId(),
        "topic_id": PydanticObjectId(),
        "current_zone": 1,
        "total_concepts": 3,
        "explanation_mode": "micro",
        "current_step_in_concept": 0,
        "current_question": None,  # deferred VTSE — no pending micro Q
        "flow_state": "explaining",
        "learning_state": "explaining",
        "current_mode": "normal",
        "student_questions_active": False,
        "concept_questions_active": False,
        "concept_teaching_await_vtse_done": True,
        "concept_teaching_sequence_snapshot": ["vtse", "story_hook"],
        "concept_teaching_stage_index": 0,
        "last_answer": "VTSE opening on the board",
        "zone1_timeline_cache": {"beats": [{"beat_id": "b0"}, {"beat_id": "b1"}]},
        "key_concepts": ["Stomata"],
        "concept_clusters": None,
        "current_concept": "Stomata",
        "current_concept_index": 0,
        "pedagogy_session_intro_done": True,
        "pedagogy_session_recall_done": True,
        "pedagogy_cluster_intro_done_for": 0,
        "pedagogy_cluster_curiosity_done_for": 0,
        "zone0_phase": "done",
        "flow_checkpoint_pending": False,
        "cluster_quiz_active": False,
        "cluster_teachback_active": False,
        "concept_vtse_opening_status": "ready",
        "concept_vtse_opening_for_index": 0,
    }
    defaults.update(kwargs)
    sess = SimpleNamespace(**defaults)

    async def _save() -> None:
        return None

    sess.save = _save  # type: ignore[method-assign]
    return sess


def _service(session: SimpleNamespace) -> SessionService:
    service = SessionService.__new__(SessionService)
    service.session_repository = AsyncMock()
    service.session_repository.get_by_id = AsyncMock(return_value=session)
    service._is_teacher_progression = lambda _s: True  # type: ignore[method-assign]
    service._teacher_debug_flow = lambda _s, _t: None  # type: ignore[method-assign]
    service._build_handler_context = lambda: None  # type: ignore[method-assign]
    service._get_current_concept = lambda _s, _t: "Stomata"  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_mid_vtse_question_preserves_await_and_strips_timeline() -> None:
    """
    VTSE step1/2 in flight (await_vtse_done) → student asks → tutor answers.
    Must NOT arm Concept Check / clear await / attach a new VTSE timeline.
    """
    session = _vtse_await_session()
    topic = SimpleNamespace(topic_name="Plants", key_concepts=["Stomata"])
    service = _service(session)

    async def _fake_explain(*_a, **_k):
        return {
            "type": "explanation",
            "message": "Good question — let's bring this back to stomata.",
            "current_concept": "Stomata",
            "instruction_timeline_v3": {"beats": [{"beat_id": "interrupt-leak"}]},
            "planner_source": "deepseek",
            "timeline_metadata": {"x": 1},
        }

    with (
        patch.object(service, "_teacher_explain_turn", new=_fake_explain),
        patch(
            "app.services.pedagogy.pedagogy_intro_service.PedagogyIntroService.maybe_emit",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.pedagogy.pedagogy_recall_curiosity_service."
            "PedagogyRecallCuriosityService.maybe_emit",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.pedagogy.concept_teaching_orchestrator."
            "ConceptTeachingOrchestrator.maybe_emit",
            new=AsyncMock(return_value=None),
        ),
    ):
        out = await service._teacher_handle_conversation(
            session,
            session.id,
            PydanticObjectId(),
            "Why do stomata open during the day?",
            topic,
            is_quiz_mode=False,
        )

    assert out is not None
    assert out.get("type") == "explanation"
    assert "instruction_timeline_v3" not in out
    assert "planner_source" not in out
    assert out.get("vtse_question_interrupt") == 1
    assert out.get("concept_teaching_await_vtse_done") == 1
    assert session.concept_teaching_await_vtse_done is True
    assert session.concept_questions_active is False
    assert session.flow_state != "concept_questions"


@pytest.mark.asyncio
async def test_no_question_continue_does_not_use_interrupt_path() -> None:
    """Plain 'no' / continue text is not a question interrupt."""
    assert SessionService._looks_like_question_interrupt("no") is False
    assert SessionService._looks_like_question_interrupt("continue") is False
    assert SessionService._looks_like_question_interrupt("Why?") is True
