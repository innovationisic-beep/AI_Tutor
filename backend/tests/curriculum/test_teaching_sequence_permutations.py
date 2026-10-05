"""Handoff coverage for every Story Hook / VTSE / Visual Teaching order.

These tests use an authored snapshot only. Content planners are stubbed.
Stage advance, Concept Check, and restore are the real orchestrator.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)

PERMUTATIONS = (
    ["story_hook", "vtse", "visual_teaching"],
    ["story_hook", "visual_teaching", "vtse"],
    ["vtse", "story_hook", "visual_teaching"],
    ["vtse", "visual_teaching", "story_hook"],
    ["visual_teaching", "story_hook", "vtse"],
    ["visual_teaching", "vtse", "story_hook"],
)


def _session(sequence: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=None,
        current_zone=1,
        zone0_phase="done",
        total_concepts=1,
        current_step_in_concept=0,
        current_concept_index=0,
        current_concept="cell",
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=list(sequence),
        concept_teaching_stage_index=0,
        concept_teaching_story_hook_snapshot={"title": "Leaf", "body": "A door opens."},
        concept_teaching_visual_teaching_snapshot={
            "images": [
                {
                    "asset_key": "leaf",
                    "storage_key": "leaf.png",
                    "title": "Leaf",
                    "teaching_purpose": "Show the pore",
                }
            ]
        },
        concept_teaching_await_vtse_done=False,
        concept_questions_active=False,
        concept_vtse_opening_status="unclaimed",
        concept_vtse_opening_for_index=-1,
        flow_state="idle",
        flow_checkpoint_pending=False,
        zone1_board_concept_id="cell",
        zone1_last_completed_beat_index=-1,
        zone1_timeline_cache={
            "timeline_id": "tl-cell",
            "beats": [{"index": 0}, {"index": 1}],
        },
        story_hook_plan=None,
        story_hook_step_index=0,
        story_hook_status="idle",
        visual_teaching_status="idle",
        current_question=None,
        save=AsyncMock(),
    )


def _stage_done() -> str:
    payload = {
        "concept_index": 0,
        "concept_id": "cell",
        "timeline_id": "tl-cell",
        "final_beat_index": 1,
    }
    return f"__action:concept_vtse_stage_done|{json.dumps(payload)}"


async def _emit_story_hook(session):
    session.story_hook_plan = {
        "steps": [{"type": "narration", "text": "Once there was a leaf."}],
        "language": "english",
        "source": "fallback",
        "writing_mode": "legacy",
    }
    session.story_hook_step_index = 0
    session.story_hook_status = "playing"
    session.flow_state = "concept_story_hook"
    return {"type": "concept_story_hook", "flow_state": "concept_story_hook"}


async def _emit_visual(session):
    session.visual_teaching_status = "playing"
    session.flow_state = "concept_visual_teaching"
    return {"type": "concept_visual_teaching", "flow_state": "concept_visual_teaching"}


async def _open_vtse(session, **_kwargs):
    """Content opener only. The completion handler must already be on VTSE."""
    seq = list(session.concept_teaching_sequence_snapshot)
    idx = int(session.concept_teaching_stage_index)
    assert seq[idx] == "vtse"
    session.concept_teaching_await_vtse_done = True
    session.concept_vtse_opening_status = "ready"
    session.concept_vtse_opening_for_index = 0
    session.flow_state = "explaining"
    session.zone1_last_completed_beat_index = 1
    return {"type": "explanation", "message": "vtse"}


async def _arm(_ctx, session, *_args, **_kwargs):
    session.concept_questions_active = True
    session.current_question = "What opened?"
    session.flow_state = "concept_questions"


async def _claim(*_args, **_kwargs):
    return {"claimed": True}


async def _leave_visual(*_args, **_kwargs):
    return {"flow_state": "concept_visual_teaching", "visual_teaching_status": "playing"}


def _patches(orch: ConceptTeachingOrchestrator):
    return (
        patch.object(orch, "_emit_story_hook_step", side_effect=_emit_story_hook),
        patch.object(orch, "_emit_visual_teaching_beat", side_effect=_emit_visual),
        patch.object(orch, "_start_vtse_after_hook", side_effect=_open_vtse),
        patch(
            "app.services.visual_teaching.runtime.atomic_claim_leave_visual_teaching",
            side_effect=_leave_visual,
        ),
        patch(
            "app.services.pedagogy.vtse_opening_claim.atomic_claim_vtse_opening",
            side_effect=_claim,
        ),
        patch(
            "app.services.handlers.concept_question_orchestrator.arm_concept_questions_after_opening",
            side_effect=_arm,
        ),
    )


async def _enter(orch: ConceptTeachingOrchestrator, session, stage: str):
    kwargs = {
        "handler_ctx": object(),
        "session_id": object(),
        "student_id": object(),
        "topic": object(),
    }
    if stage == "vtse":
        opened = await orch.maybe_emit(session, action=None, **kwargs)
        assert opened is None
        assert orch.current_stage(session) == "vtse"
        assert orch.mark_vtse_opening_started(session) is True
        session.concept_vtse_opening_status = "ready"
        session.concept_vtse_opening_for_index = 0
        session.flow_state = "explaining"
        session.zone1_last_completed_beat_index = 1
        return {"type": "vtse"}
    opened = await orch.maybe_emit(session, action=None, **kwargs)
    assert opened is not None
    if stage == "story_hook":
        assert opened["type"] == "concept_story_hook"
    else:
        assert opened["type"] == "concept_visual_teaching"
    return opened


async def _complete(orch: ConceptTeachingOrchestrator, session, stage: str):
    kwargs = {
        "handler_ctx": object(),
        "session_id": object(),
        "student_id": object(),
        "topic": object(),
    }
    if stage == "story_hook":
        session.flow_state = "concept_story_hook"
        return await orch.maybe_emit(session, action="story_hook_done", **kwargs)
    if stage == "visual_teaching":
        session.flow_state = "concept_visual_teaching"
        session.visual_teaching_status = "done"
        return await orch.maybe_emit(session, action="visual_teaching_done", **kwargs)
    session.flow_state = "explaining"
    session.concept_teaching_await_vtse_done = True
    session.concept_vtse_opening_status = "ready"
    session.concept_vtse_opening_for_index = 0
    session.zone1_last_completed_beat_index = 1
    return await orch.maybe_emit(
        session,
        action="concept_vtse_stage_done",
        user_input=_stage_done(),
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sequence", PERMUTATIONS)
async def test_permutation_handoff_concept_check_and_restore(sequence: list[str]) -> None:
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _session(sequence)
    patches = _patches(orch)
    for item in patches:
        item.start()
    try:
        await _enter(orch, session, sequence[0])
        for index, stage in enumerate(sequence):
            assert orch.current_stage(session) == stage
            assert session.concept_questions_active is False
            if stage == "vtse":
                assert session.concept_teaching_stage_index == sequence.index("vtse")
            frozen = list(session.concept_teaching_sequence_snapshot)
            cursor = session.concept_teaching_stage_index
            restored = await orch.ensure_sequence_snapshot(session)
            assert restored == frozen == sequence
            assert session.concept_teaching_stage_index == cursor

            result = await _complete(orch, session, stage)
            assert list(session.concept_teaching_sequence_snapshot) == sequence
            if index < len(sequence) - 1:
                nxt = sequence[index + 1]
                assert session.concept_questions_active is False, (
                    stage,
                    result,
                    session.concept_teaching_stage_index,
                    session.flow_state,
                )
                assert orch.current_stage(session) == nxt, (
                    stage,
                    getattr(result, "get", lambda *_a: result)("type")
                    if isinstance(result, dict)
                    else result,
                    session.flow_state,
                    session.visual_teaching_status,
                    session.concept_vtse_opening_status,
                    session.concept_teaching_stage_index,
                )
                if nxt == "vtse":
                    assert result is not None
                    assert result.get("type") == "explanation"
                    session.flow_state = "explaining"
                    session.concept_vtse_opening_status = "ready"
                    session.concept_vtse_opening_for_index = 0
                    session.concept_teaching_await_vtse_done = True
                    session.zone1_last_completed_beat_index = 1
                elif nxt == "story_hook":
                    assert result["type"] == "concept_story_hook"
                else:
                    assert result["type"] == "concept_visual_teaching"
            else:
                assert result["type"] == "concept_question"
                assert session.concept_questions_active is True

        frozen = list(session.concept_teaching_sequence_snapshot)
        cursor = session.concept_teaching_stage_index
        restored = await orch.ensure_sequence_snapshot(session)
        assert restored == frozen == sequence
        assert session.concept_teaching_stage_index == cursor
        assert session.concept_questions_active is True
    finally:
        for item in reversed(patches):
            item.stop()
