"""Visual Teaching concurrency / deadlock contract tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)
from app.services.visual_teaching import runtime as vt_runtime


def _playing_session(**kwargs):
    base = dict(
        flow_state="concept_visual_teaching",
        visual_teaching_status="playing",
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=-1,
        visual_teaching_plan={
            "scenes": [
                {
                    "asset_key": "a",
                    "beats": [
                        {"id": "b0", "speak": "One. Two.", "visual_state": {}},
                        {"id": "b1", "speak": "Three.", "visual_state": {}},
                    ],
                },
                {
                    "asset_key": "b",
                    "beats": [
                        {"id": "b2", "speak": "Four.", "visual_state": {}},
                    ],
                },
            ]
        },
        concept_teaching_sequence_snapshot=["visual_teaching"],
        concept_teaching_stage_index=0,
        concept_teaching_visual_teaching_snapshot={
            "images": [
                {
                    "id": "1",
                    "asset_key": "a",
                    "storage_key": "a.jpg",
                    "teaching_purpose": "x",
                    "natural_width": 100,
                    "natural_height": 100,
                },
                {
                    "id": "2",
                    "asset_key": "b",
                    "storage_key": "b.jpg",
                    "teaching_purpose": "y",
                    "natural_width": 100,
                    "natural_height": 100,
                },
            ]
        },
        current_zone=1,
        zone0_phase="done",
        concept_teaching_await_vtse_done=False,
        key_concept_ids=["c1"],
        current_concept_index=0,
        current_concept="Concept",
        visual_teaching_skipped_scenes=[],
    )
    base.update(kwargs)
    session = SimpleNamespace(**base)
    session.save = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_sentence_action_returns_ack_not_noop():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _playing_session()
    result = await orch.maybe_emit(
        session, action="visual_teaching_sentence:0:0:0"
    )
    assert result["type"] == "visual_teaching_sentence_ack"
    assert result["accepted"] is True
    assert session.visual_teaching_sentence_index == 0


@pytest.mark.asyncio
async def test_stale_sentence_ack_does_not_mutate_cursor():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _playing_session(
        visual_teaching_beat_index=1,
        visual_teaching_sentence_index=0,
    )
    result = await orch.maybe_emit(
        session, action="visual_teaching_sentence:0:0:5"
    )
    assert result["type"] == "visual_teaching_sentence_ack"
    assert result["accepted"] is False
    assert session.visual_teaching_sentence_index == 0


@pytest.mark.asyncio
async def test_done_reconciles_when_status_done_flow_still_vt():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _playing_session(
        visual_teaching_status="done",
        visual_teaching_scene_index=2,
        visual_teaching_beat_index=0,
    )
    armed = {"n": 0}

    async def fake_arm(*_a, **_k):
        armed["n"] += 1
        return {"type": "explanation", "message": "Q1"}

    with patch.object(
        orch, "_arm_post_concept_questions", side_effect=fake_arm
    ):
        first = await orch.maybe_emit(session, action="visual_teaching_done")
        assert first["type"] == "explanation"
        assert armed["n"] == 1
        assert session.flow_state == "idle"
        assert session.concept_teaching_stage_index == 1
        # Second done: already past → terminal advance ack, questions not re-armed.
        second = await orch.maybe_emit(session, action="visual_teaching_done")
        assert second["type"] == "visual_teaching_advance_ack"
        assert second["outcome"] == "already_advanced"
        assert armed["n"] == 1


@pytest.mark.asyncio
async def test_two_scene_integration_to_done():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = _playing_session()
    armed = {"n": 0}

    async def exists(_key: str) -> bool:
        return True

    async def fake_arm(*_a, **_k):
        armed["n"] += 1
        return {"type": "explanation", "message": "armed"}

    with patch(
        "app.services.visual_teaching.runtime.get_visual_teaching_storage",
        return_value=SimpleNamespace(exists=exists),
    ), patch.object(
        orch, "_resolve_current_concept", AsyncMock(return_value=None)
    ), patch.object(orch, "_arm_post_concept_questions", side_effect=fake_arm):
        # beat 0 → beat 1 (same scene)
        r0 = await orch.maybe_emit(session, action="visual_teaching_next")
        assert r0["type"] == "concept_visual_teaching"
        assert session.visual_teaching_scene_index == 0
        assert session.visual_teaching_beat_index == 1
        assert session.visual_teaching_sentence_index == -1
        # beat 1 → scene 1 beat 0
        r1 = await orch.maybe_emit(session, action="visual_teaching_next")
        assert r1["type"] == "concept_visual_teaching"
        assert session.visual_teaching_scene_index == 1
        assert session.visual_teaching_beat_index == 0
        assert session.visual_teaching_sentence_index == -1
        # last beat → done → arm questions once
        r2 = await orch.maybe_emit(session, action="visual_teaching_done")
        assert r2["type"] == "explanation"
        assert armed["n"] == 1
        assert session.visual_teaching_status == "done"
        assert session.flow_state == "idle"
        # Duplicate done does not re-arm — terminal VT-complete ack.
        r3 = await orch.maybe_emit(session, action="visual_teaching_done")
        assert r3["type"] == "visual_teaching_advance_ack"
        assert r3["outcome"] == "already_advanced"
        assert armed["n"] == 1


def test_advance_beat_resets_sentence_index():
    session = SimpleNamespace(
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=3,
    )
    plan = vt_runtime.VisualTeachingPlan.model_validate(
        {
            "scenes": [
                {
                    "asset_key": "a",
                    "beats": [
                        {"id": "b0", "speak": "A.", "visual_state": {}},
                        {"id": "b1", "speak": "B.", "visual_state": {}},
                    ],
                }
            ]
        }
    )
    done = vt_runtime.advance_beat(session, plan)
    assert done is True
    assert session.visual_teaching_beat_index == 1
    assert session.visual_teaching_sentence_index == -1


def test_sentence_monotonic_within_beat_only():
    session = SimpleNamespace(
        visual_teaching_status="playing",
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=2,
    )
    assert (
        vt_runtime.record_sentence_progress(
            session, 1, scene_index=0, beat_index=0
        )
        is False
    )
    assert (
        vt_runtime.record_sentence_progress(
            session, 3, scene_index=0, beat_index=0
        )
        is True
    )
    assert session.visual_teaching_sentence_index == 3
