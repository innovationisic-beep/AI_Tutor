"""Tests for concept teaching sequence helpers and orchestrator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services.curriculum.concept_teaching_sequence import (
    ConceptStoryHook,
    dedupe_asset_key,
    normalize_asset_key,
    normalize_story_hook,
    normalize_story_hook_visuals,
    resolve_effective_teaching_sequence,
    validate_teaching_sequence,
)
from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
    zone0_blocks_concept_teaching,
)


def test_legacy_default_is_vtse_only():
    assert resolve_effective_teaching_sequence(
        teaching_sequence=None,
        story_hook=None,
    ) == ["vtse"]
    assert resolve_effective_teaching_sequence(
        teaching_sequence=[],
        story_hook=None,
    ) == ["vtse"]


def test_story_hook_only_when_content_exists():
    hook = ConceptStoryHook(title="Once", body="upon a time")
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["story_hook"],
        story_hook=hook,
    ) == ["story_hook"]


def test_vtse_then_story_hook():
    hook = ConceptStoryHook(title="Hook", body="Body")
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["vtse", "story_hook"],
        story_hook=hook,
    ) == ["vtse", "story_hook"]


def test_story_hook_then_vtse():
    hook = ConceptStoryHook(title="Hook", body="Body")
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["story_hook", "vtse"],
        story_hook=hook,
    ) == ["story_hook", "vtse"]


def test_full_sequence_always_skips_retired_media():
    hook = ConceptStoryHook(title="Hook", body="Body")
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["vtse", "story_hook", "media"],
        story_hook=hook,
        media_available=False,
    ) == ["vtse", "story_hook"]
    # media_available no longer enables media — Visual Teaching replaced it.
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["vtse", "story_hook", "media"],
        story_hook=hook,
        media_available=True,
    ) == ["vtse", "story_hook"]


def test_duplicate_sequence_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_teaching_sequence(["vtse", "vtse"])
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "DUPLICATE_TEACHING_STAGE"


def test_invalid_sequence_stage_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_teaching_sequence(["vtse", "fact"])
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "INVALID_TEACHING_STAGE"


def test_visual_teaching_alone_and_before_vtse_resolve():
    vt = {
        "images": [
            {
                "asset_key": "leaf",
                "storage_key": "leaf.png",
                "mime_type": "image/png",
                "title": "Leaf",
                "teaching_purpose": "Pore",
                "natural_width": 10,
                "natural_height": 10,
                "content_hash": "abc",
                "annotations_status": "confirmed",
                "regions": [
                    {
                        "region_id": "pore",
                        "label": "Pore",
                        "shape": "rect",
                        "geometry": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    }
                ],
                "anchors": [],
                "connections": [],
            }
        ]
    }
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["visual_teaching"],
        story_hook=None,
        visual_teaching=vt,
    ) == ["visual_teaching"]
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["visual_teaching", "vtse"],
        story_hook=None,
        visual_teaching=vt,
    ) == ["visual_teaching", "vtse"]
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["story_hook", "visual_teaching", "vtse"],
        story_hook=ConceptStoryHook(title="T", body="B"),
        visual_teaching=vt,
    ) == ["story_hook", "visual_teaching", "vtse"]


def test_missing_story_hook_content_skipped():
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["story_hook", "vtse"],
        story_hook=None,
    ) == ["vtse"]
    assert resolve_effective_teaching_sequence(
        teaching_sequence=["story_hook", "vtse"],
        story_hook=ConceptStoryHook(title="", body=""),
    ) == ["vtse"]


def test_normalize_story_hook_empty_is_none():
    assert normalize_story_hook({"title": "  ", "body": ""}) is None
    hook = normalize_story_hook({"title": "A", "body": "B"})
    assert hook is not None
    assert hook.title == "A"
    assert hook.body == "B"


@pytest.mark.asyncio
async def test_orchestrator_story_hook_then_vtse_order():
    orch = ConceptTeachingOrchestrator(concept_repo=MagicMock())
    session = SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        current_concept_index=0,
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=["story_hook", "vtse"],
        concept_teaching_stage_index=0,
        concept_teaching_story_hook_snapshot={"title": "T", "body": "B"},
        concept_teaching_await_vtse_done=False,
        flow_state="idle",
        concept_questions_active=False,
        current_concept="cell",
        current_question=None,
        save=AsyncMock(),
    )

    first = await orch.maybe_emit(session, action=None)
    assert first is not None
    assert first["type"] == "concept_story_hook"
    assert first["flow_state"] == "concept_story_hook"
    session.flow_state = "concept_story_hook"

    second = await orch.maybe_emit(session, action="story_hook_done")
    assert second is None  # fall through to existing VTSE
    assert session.concept_teaching_stage_index == 1
    assert session.flow_state == "idle"
    assert orch.current_stage(session) == "vtse"


@pytest.mark.asyncio
async def test_orchestrator_vtse_then_story_hook_order():
    orch = ConceptTeachingOrchestrator(concept_repo=MagicMock())
    session = SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        current_concept_index=0,
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=["vtse", "story_hook"],
        concept_teaching_stage_index=0,
        concept_teaching_story_hook_snapshot={"title": "T", "body": "B"},
        concept_teaching_await_vtse_done=False,
        flow_state="idle",
        concept_questions_active=False,
        current_concept="cell",
        current_question="Q1?",
        zone1_timeline_cache={
            "timeline_id": "tl-cell",
            "beats": [{"index": 0}, {"index": 1}],
        },
        zone1_board_concept_id="cell",
        zone1_last_completed_beat_index=1,
        concept_vtse_opening_status="unclaimed",
        concept_vtse_opening_for_index=-1,
        flow_checkpoint_pending=False,
        save=AsyncMock(),
    )

    # Pre-VTSE: idle emit returns None → VTSE runs
    assert await orch.maybe_emit(session, action=None) is None
    defer = orch.mark_vtse_opening_started(session)
    assert defer is True
    assert session.concept_teaching_await_vtse_done is True
    assert session.concept_teaching_stage_index == 0

    session.flow_state = "explaining"
    session.concept_vtse_opening_status = "ready"
    session.concept_vtse_opening_for_index = 0
    after_vtse = await orch.maybe_emit(
        session,
        action="concept_vtse_stage_done",
        user_input=(
            '__action:concept_vtse_stage_done|'
            '{"concept_index":0,"concept_id":"cell","timeline_id":"tl-cell"}'
        ),
    )
    assert after_vtse is not None
    assert after_vtse["type"] == "concept_story_hook"
    assert orch.current_stage(session) == "story_hook"


@pytest.mark.asyncio
async def test_orchestrator_media_stage_never_executes_implementation():
    orch = ConceptTeachingOrchestrator(concept_repo=MagicMock())
    session = SimpleNamespace(
        current_zone=1,
        zone0_phase="done",
        current_concept_index=0,
        concept_teaching_for_index=0,
        # Snapshot already resolved without media normally; force media to prove skip.
        concept_teaching_sequence_snapshot=["media", "vtse"],
        concept_teaching_stage_index=0,
        concept_teaching_story_hook_snapshot=None,
        concept_teaching_await_vtse_done=False,
        flow_state="idle",
        save=AsyncMock(),
    )
    result = await orch.maybe_emit(session, action=None)
    assert result is None
    assert session.concept_teaching_stage_index == 1
    assert orch.current_stage(session) == "vtse"


def test_zone0_blocks_until_phase_done():
    assert zone0_blocks_concept_teaching(
        SimpleNamespace(current_zone=0, zone0_phase="ready")
    )
    assert zone0_blocks_concept_teaching(
        SimpleNamespace(current_zone=0, zone0_phase="anchor")
    )
    assert not zone0_blocks_concept_teaching(
        SimpleNamespace(current_zone=0, zone0_phase="done")
    )
    assert not zone0_blocks_concept_teaching(
        SimpleNamespace(current_zone=1, zone0_phase="ready")
    )


@pytest.mark.asyncio
async def test_zone0_gate_clears_story_hook_flow_without_save():
    orch = ConceptTeachingOrchestrator(concept_repo=MagicMock())
    session = SimpleNamespace(
        current_zone=0,
        zone0_phase="ready",
        flow_state="concept_story_hook",
        concept_teaching_await_vtse_done=True,
        save=AsyncMock(),
    )
    assert await orch.maybe_emit(session, action=None) is None
    assert session.flow_state == "idle"
    assert session.concept_teaching_await_vtse_done is False
    session.save.assert_not_called()


def test_normalize_asset_key_underscore_slug():
    assert normalize_asset_key("Stomata Surface") == "stomata_surface"
    assert normalize_asset_key("living thing") == "living_thing"
    assert normalize_asset_key("living_thing") == "living_thing"
    assert normalize_asset_key("Living-Thing!!") == "living_thing"
    assert normalize_asset_key("") == "visual"
    assert normalize_asset_key("  ", fallback="visual_3") == "visual_3"
    assert len(normalize_asset_key("a" * 80)) == 64


def test_dedupe_asset_key_suffixes():
    assert dedupe_asset_key("leaf", []) == "leaf"
    assert dedupe_asset_key("leaf", ["leaf"]) == "leaf-2"
    assert dedupe_asset_key("leaf", ["leaf", "leaf-2"]) == "leaf-3"


def test_normalize_story_hook_visuals_drops_missing_storage_and_dedupes():
    out = normalize_story_hook_visuals(
        [
            {
                "asset_key": "Leaf Surface",
                "storage_key": "sk_a",
                "description": "pores",
            },
            {
                "asset_key": "leaf_surface",
                "storage_key": "sk_b",
            },
            {
                "asset_key": "orphan",
                "storage_key": "",
            },
        ]
    )
    assert [v.asset_key for v in out] == ["leaf_surface", "leaf_surface-2"]
    assert all(v.storage_key for v in out)