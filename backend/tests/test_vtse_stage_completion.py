"""VTSE playback must finish before Concept Check, including sequence [\"vtse\"]."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)
from app.services.pedagogy.vtse_stage_completion import can_complete_vtse_stage
from app.services.session_service import SessionService

TEMPLATES = (
    "linear_process",
    "hierarchy_concept_intro",
    "clustered_trait_list",
    "comparison_contrast",
    "cycle_process",
)


def _beats(n: int) -> list[dict]:
    return [{"beat_id": f"b{i}", "index": i} for i in range(n)]


def _session(*, beats: int, cursor: int, pending: bool = False, sequence=None):
    sequence = list(sequence or ["vtse"])
    return SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        current_concept_index=0,
        current_concept="cell",
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=sequence,
        concept_teaching_stage_index=sequence.index("vtse"),
        concept_teaching_story_hook_snapshot={"title": "T", "body": "B"},
        concept_teaching_visual_teaching_snapshot={"scenes": [{"id": "s"}]},
        concept_teaching_await_vtse_done=True,
        concept_questions_active=False,
        concept_vtse_opening_status="ready",
        concept_vtse_opening_for_index=0,
        flow_state="explaining",
        flow_checkpoint_pending=pending,
        zone1_board_concept_id="cell",
        zone1_last_completed_beat_index=cursor,
        zone1_timeline_cache={"timeline_id": "tl-cell", "beats": _beats(beats)},
        save=AsyncMock(),
    )


def _identity(**overrides):
    body = {
        "concept_index": 0,
        "concept_id": "cell",
        "timeline_id": "tl-cell",
        "board_item_id": "board-1",
    }
    body.update(overrides)
    return body


def _action(identity=None):
    payload = _identity() if identity is None else identity
    return f"__action:concept_vtse_stage_done|{json.dumps(payload)}"


def test_opening_for_vtse_only_does_not_arm_questions():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _session(beats=6, cursor=-1)
    session.concept_teaching_await_vtse_done = False
    session.zone1_last_completed_beat_index = None
    assert orch.mark_vtse_opening_started(session) is True
    assert session.concept_questions_active is False
    assert session.concept_teaching_await_vtse_done is True
    assert session.concept_teaching_stage_index == 0


@pytest.mark.parametrize("beats", [2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("template", TEMPLATES)
@pytest.mark.parametrize("tts_on", [True, False])
def test_linear_and_other_templates_reject_until_final_beat(beats, template, tts_on):
    """TTS and template id are not completion signals. Beat cursor is."""
    del template, tts_on
    session = _session(beats=beats, cursor=max(0, beats - 2))
    ok, reason = can_complete_vtse_stage(session, _identity())
    assert ok is False
    assert reason == "beat_incomplete"


@pytest.mark.parametrize("beats", [2, 4, 6, 8, 3, 5, 7])
def test_checkpoint_pending_blocks_even_on_final_cursor(beats):
    session = _session(beats=beats, cursor=beats - 1, pending=True)
    ok, reason = can_complete_vtse_stage(session, _identity())
    assert ok is False
    assert reason == "checkpoint_pending"


@pytest.mark.parametrize("beats", [2, 4, 6, 8, 3, 5, 7])
def test_continue_clears_pending_but_still_needs_final_beat(beats):
    session = _session(beats=beats, cursor=max(0, beats - 2), pending=False)
    ok, reason = can_complete_vtse_stage(session, _identity())
    assert ok is False
    assert reason == "beat_incomplete"


def test_final_beat_and_cleared_checkpoint_accepts():
    session = _session(beats=6, cursor=5, pending=False)
    ok, reason = can_complete_vtse_stage(session, _identity())
    assert ok is True
    assert reason == "ok"


def test_lagging_cursor_accepts_when_stage_done_names_final_beat():
    session = _session(beats=6, cursor=1, pending=False)
    ok, reason = can_complete_vtse_stage(
        session, _identity(final_beat_index=5)
    )
    assert ok is True
    assert reason == "ok"
    assert session.zone1_last_completed_beat_index == 5


def test_open_checkpoint_blocks_final_beat_claim():
    session = _session(beats=6, cursor=5, pending=True)
    ok, reason = can_complete_vtse_stage(
        session, _identity(final_beat_index=5)
    )
    assert ok is False
    assert reason == "checkpoint_pending"


def test_omitted_timeline_id_uses_the_active_timeline():
    from app.services.pedagogy.vtse_stage_completion import bind_active_vtse_timeline

    session = _session(beats=6, cursor=1, pending=False)
    bound = bind_active_vtse_timeline(session, {"final_beat_index": 5})
    ok, reason = can_complete_vtse_stage(session, bound)
    assert ok is True
    assert reason == "ok"
    assert session.zone1_last_completed_beat_index == 5


def test_missing_identity_uses_cache_when_cursor_is_final():
    """TTS-off text completion often omits timeline_id after the last beat."""
    session = _session(beats=4, cursor=3)
    ok, reason = can_complete_vtse_stage(session, None)
    assert ok is True
    assert reason == "ok"
    early = _session(beats=4, cursor=1)
    ok, reason = can_complete_vtse_stage(early, None)
    assert ok is False
    assert reason == "beat_incomplete"
    ok, reason = can_complete_vtse_stage(
        session, _identity(timeline_id="tl-other")
    )
    assert ok is False
    assert reason == "timeline_mismatch"


def test_quiz_finishes_only_when_the_cached_timeline_is_done():
    session = _session(beats=4, cursor=3)
    ok, reason = can_complete_vtse_stage(session, None)
    assert ok is True
    assert reason == "ok"
    early = _session(beats=4, cursor=0)
    ok, reason = can_complete_vtse_stage(early, None)
    assert ok is False
    assert reason == "beat_incomplete"


@pytest.mark.asyncio
async def test_stage_done_arms_only_after_true_completion():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _session(beats=6, cursor=1)
    early = await orch.maybe_emit(
        session,
        action="concept_vtse_stage_done",
        user_input=_action(),
        handler_ctx=object(),
        session_id=object(),
        student_id=object(),
        topic=object(),
    )
    assert early["type"] == "noop"
    assert early["vtse_stage_complete"] is False
    assert session.concept_questions_active is False
    assert session.concept_teaching_await_vtse_done is True

    session.zone1_last_completed_beat_index = 5
    session.flow_checkpoint_pending = True
    held = await orch.maybe_emit(
        session,
        action="concept_vtse_stage_done",
        user_input=_action(),
        handler_ctx=object(),
        session_id=object(),
        student_id=object(),
        topic=object(),
    )
    assert held["reason"] == "checkpoint_pending"
    assert session.concept_questions_active is False

    session.flow_checkpoint_pending = False

    async def _arm(*_a, **_k):
        session.concept_questions_active = True

    with patch(
        "app.services.handlers.concept_question_orchestrator.arm_concept_questions_after_opening",
        side_effect=_arm,
    ):
        done = await orch.maybe_emit(
            session,
            action="concept_vtse_stage_done",
            user_input=_action(),
            handler_ctx=object(),
            session_id=object(),
            student_id=object(),
            topic=object(),
        )
    assert done["type"] == "concept_question"
    assert session.concept_questions_active is True
    assert session.concept_teaching_await_vtse_done is False


@pytest.mark.asyncio
async def test_vtse_then_visual_teaching_does_not_arm_questions():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _session(
        beats=4,
        cursor=3,
        sequence=["vtse", "visual_teaching"],
    )

    async def _emit(*_a, **_k):
        return {"type": "concept_visual_teaching", "flow_state": "concept_visual_teaching"}

    with (
        patch.object(orch, "_skip_non_executable_stages", return_value="visual_teaching"),
        patch.object(orch, "_emit_visual_teaching_beat", side_effect=_emit),
    ):
        out = await orch.maybe_emit(
            session,
            action="concept_vtse_stage_done",
            user_input=_action(),
            handler_ctx=object(),
            session_id=object(),
            student_id=object(),
            topic=object(),
        )
    assert out["type"] == "concept_visual_teaching"
    assert session.concept_questions_active is False
    assert session.concept_teaching_stage_index == 1


@pytest.mark.asyncio
async def test_story_hook_vtse_visual_does_not_arm_between_stages():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _session(
        beats=3,
        cursor=0,
        sequence=["story_hook", "vtse", "visual_teaching"],
    )

    async def _emit(*_a, **_k):
        return {"type": "concept_visual_teaching"}

    with patch.object(orch, "_emit_visual_teaching_beat", side_effect=_emit):
        out = await orch.maybe_emit(
            session,
            action="understand",
            user_input="I understand",
            handler_ctx=object(),
            session_id=object(),
            student_id=object(),
            topic=object(),
        )
    assert out["type"] == "noop"
    assert session.concept_questions_active is False
    assert session.concept_teaching_await_vtse_done is True

    session.zone1_last_completed_beat_index = 2
    with (
        patch.object(orch, "_skip_non_executable_stages", return_value="visual_teaching"),
        patch.object(orch, "_emit_visual_teaching_beat", side_effect=_emit),
    ):
        out = await orch.maybe_emit(
            session,
            action="concept_vtse_stage_done",
            user_input=_action(),
            handler_ctx=object(),
            session_id=object(),
            student_id=object(),
            topic=object(),
        )
    assert out["type"] == "concept_visual_teaching"
    assert session.concept_questions_active is False


def test_restore_matrix_does_not_surface_early_concept_check():
    def suppress(**kwargs):
        session = SimpleNamespace(
            concept_questions_active=kwargs.get("active", False),
            concept_question_index=0,
            concept_teaching_await_vtse_done=kwargs.get("awaiting", True),
            flow_checkpoint_pending=kwargs.get("pending", False),
            flow_state=kwargs.get("flow", "explaining"),
            current_question=kwargs.get("question"),
        )
        return SessionService._restore_should_suppress_concept_questions(session, [])

    assert suppress(active=False, awaiting=True) is False
    assert suppress(active=True, awaiting=True, pending=True) is True
    assert suppress(active=False, awaiting=True, pending=False) is False
    assert (
        suppress(
            active=True,
            awaiting=False,
            pending=False,
            flow="concept_questions",
            question="What is step one?",
        )
        is False
    )
