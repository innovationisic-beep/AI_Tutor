"""Hardening tests for Visual Teaching contract completion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.curriculum.concept_teaching_sequence import validate_teaching_sequence
from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
    ValidationResult,
)
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    VisualTeachingAnchor,
    VisualTeachingConnection,
    VisualTeachingImage,
    VisualTeachingRegion,
    apply_server_replace_stale,
    mark_image_annotations_stale,
)
from app.services.visual_teaching.plan_schema import (
    VisualState,
    apply_visual_state_patch,
    visual_state_at,
    VisualTeachingBeat,
    SemanticAnchorEvent,
)
from app.services.visual_teaching.validate import (
    VisualTeachingPlanError,
    validate_plan_payload,
)
from app.services.visual_teaching import runtime as vt_runtime
from app.services.pedagogy.concept_teaching_orchestrator import ConceptTeachingOrchestrator


def _pkg(**kwargs):
    return ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="leaf",
                storage_key="leaf.jpg",
                teaching_purpose="Show stomata",
                annotations_status="confirmed",
                regions=[
                    VisualTeachingRegion(
                        region_id="guard",
                        label="Guard cells",
                        shape="rect",
                        geometry={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    )
                ],
                **kwargs,
            )
        ]
    )


def test_visual_teaching_alone_allowed():
    assert validate_teaching_sequence(["visual_teaching"]) == ["visual_teaching"]


def test_visual_teaching_before_vtse_allowed():
    assert validate_teaching_sequence(["visual_teaching", "vtse"]) == [
        "visual_teaching",
        "vtse",
    ]


def test_story_hook_visual_teaching_vtse_any_order():
    assert validate_teaching_sequence(
        ["story_hook", "visual_teaching", "vtse"]
    ) == ["story_hook", "visual_teaching", "vtse"]
    assert validate_teaching_sequence(
        ["visual_teaching", "story_hook"]
    ) == ["visual_teaching", "story_hook"]


def test_unsupported_capability_rejected():
    # Temporarily pretend zoom is unsupported by patching assert
    with patch(
        "app.services.visual_teaching.validate.assert_capabilities_supported",
        return_value=["zoom"],
    ):
        with pytest.raises(VisualTeachingPlanError, match="unsupported"):
            validate_plan_payload(
                {
                    "capabilities_used": ["zoom"],
                    "scenes": [
                        {
                            "asset_key": "leaf",
                            "beats": [
                                {
                                    "id": "b1",
                                    "speak": "Hi.",
                                    "visual_state": {"zoom": {"region_id": "guard"}},
                                }
                            ],
                        }
                    ],
                },
                authored=_pkg(),
            )


def test_unknown_enter_effect_rejected():
    with pytest.raises(VisualTeachingPlanError, match="enter_effect"):
        validate_plan_payload(
            {
                "scenes": [
                    {
                        "asset_key": "leaf",
                        "beats": [
                            {
                                "id": "b1",
                                "speak": "Hi.",
                                "visual_state": {},
                                "enter_effects": [{"type": "explode_region"}],
                            }
                        ],
                    }
                ]
            },
            authored=_pkg(),
        )


def test_pointer_empty_string_normalizes_to_null():
    assert VisualState(pointer="").pointer is None
    out = apply_visual_state_patch(
        VisualState(pointer="guard"), {"pointer": ""}
    )
    assert out.pointer is None


def test_replace_stale_server_enforced():
    prev = _pkg()
    incoming = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="leaf",
                storage_key="NEW.jpg",
                teaching_purpose="Show stomata",
                annotations_status="confirmed",  # client lies
                regions=prev.images[0].regions,
            )
        ]
    )
    fixed = apply_server_replace_stale(prev, incoming)
    assert fixed.images[0].annotations_status == "stale"
    assert mark_image_annotations_stale(prev.images[0]).annotations_status == "stale"


def test_reconfirm_same_binary_allows_confirmed():
    prev = _pkg()
    incoming = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="leaf",
                storage_key="leaf.jpg",
                teaching_purpose="Show stomata",
                annotations_status="confirmed",
                regions=prev.images[0].regions,
            )
        ]
    )
    fixed = apply_server_replace_stale(prev, incoming)
    assert fixed.images[0].annotations_status == "confirmed"


def test_publish_duplicate_anchor():
    svc = CurriculumValidationService()
    result = ValidationResult()
    raw = {
        "images": [
            {
                "asset_key": "leaf",
                "storage_key": "leaf.jpg",
                "teaching_purpose": "x",
                "annotations_status": "confirmed",
                "regions": [
                    {
                        "region_id": "guard",
                        "shape": "rect",
                        "geometry": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    }
                ],
                "anchors": [
                    {"anchor_id": "a1", "point": {"x": 0.2, "y": 0.2}},
                    {"anchor_id": "a1", "point": {"x": 0.3, "y": 0.3}},
                ],
            }
        ]
    }
    concept = {
        "teaching_sequence": ["vtse", "visual_teaching"],
        "visual_teaching": raw,
    }
    svc._check_visual_teaching(
        result, concept=concept, concept_name="C", concept_path="c"
    )
    codes = {e.code for e in result.errors}
    assert "VISUAL_TEACHING_DUPLICATE_ANCHOR_ID" in codes


def test_publish_duplicate_connection():
    svc = CurriculumValidationService()
    result = ValidationResult()
    raw = {
        "images": [
            {
                "asset_key": "leaf",
                "storage_key": "leaf.jpg",
                "teaching_purpose": "x",
                "annotations_status": "confirmed",
                "regions": [
                    {
                        "region_id": "guard",
                        "shape": "rect",
                        "geometry": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    }
                ],
                "anchors": [
                    {"anchor_id": "a1", "point": {"x": 0.2, "y": 0.2}},
                    {"anchor_id": "a2", "point": {"x": 0.8, "y": 0.8}},
                ],
                "connections": [
                    {"connection_id": "c1", "from_anchor": "a1", "to_anchor": "a2"},
                    {"connection_id": "c1", "from_anchor": "a2", "to_anchor": "a1"},
                ],
            }
        ]
    }
    concept = {
        "teaching_sequence": ["vtse", "visual_teaching"],
        "visual_teaching": raw,
    }
    svc._check_visual_teaching(
        result, concept=concept, concept_name="C", concept_path="c"
    )
    assert any(e.code == "VISUAL_TEACHING_DUPLICATE_CONNECTION_ID" for e in result.errors)


def test_publish_invalid_arrow_connection():
    """Authored arrows (connections) must reference real, distinct anchors."""
    svc = CurriculumValidationService()
    result = ValidationResult()
    raw = {
        "images": [
            {
                "asset_key": "leaf",
                "storage_key": "leaf.jpg",
                "teaching_purpose": "x",
                "annotations_status": "confirmed",
                "regions": [],
                "anchors": [
                    {"anchor_id": "arrow_1_from", "point": {"x": 0.2, "y": 0.2}},
                    {"anchor_id": "arrow_1_to", "point": {"x": 0.8, "y": 0.8}},
                ],
                "connections": [
                    {
                        "connection_id": "arrow_1",
                        "from_anchor": "arrow_1_from",
                        "to_anchor": "missing",
                        "kind": "flow",
                    },
                    {
                        "connection_id": "arrow_2",
                        "from_anchor": "arrow_1_from",
                        "to_anchor": "arrow_1_from",
                        "kind": "flow",
                    },
                ],
            }
        ]
    }
    concept = {
        "teaching_sequence": ["vtse", "visual_teaching"],
        "visual_teaching": raw,
    }
    svc._check_visual_teaching(
        result, concept=concept, concept_name="C", concept_path="c"
    )
    codes = [e.code for e in result.errors]
    assert codes.count("VISUAL_TEACHING_INVALID_CONNECTION") >= 2


def test_publish_invalid_geometry():
    svc = CurriculumValidationService()
    result = ValidationResult()
    raw = {
        "images": [
            {
                "asset_key": "leaf",
                "storage_key": "leaf.jpg",
                "teaching_purpose": "x",
                "annotations_status": "confirmed",
                "regions": [
                    {
                        "region_id": "guard",
                        "shape": "rect",
                        "geometry": {"x": 1.5, "y": 0.1, "w": 0.2, "h": 0.2},
                    }
                ],
            }
        ]
    }
    concept = {
        "teaching_sequence": ["vtse", "visual_teaching"],
        "visual_teaching": raw,
    }
    svc._check_visual_teaching(
        result, concept=concept, concept_name="C", concept_path="c"
    )
    assert any(e.code == "VISUAL_TEACHING_INVALID_GEOMETRY" for e in result.errors)


def test_publish_allows_visual_teaching_without_vtse():
    svc = CurriculumValidationService()
    result = ValidationResult()
    concept = {
        "teaching_sequence": ["visual_teaching"],
        "visual_teaching": _pkg().model_dump(),
    }
    svc._check_visual_teaching(
        result, concept=concept, concept_name="C", concept_path="c"
    )
    assert not any(e.code == "VISUAL_TEACHING_REQUIRES_VTSE" for e in result.errors)
    assert not any(e.code == "VISUAL_TEACHING_BEFORE_VTSE" for e in result.errors)


def test_sentence_progress_idempotent():
    session = SimpleNamespace(
        visual_teaching_status="playing",
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=1,
        visual_teaching_sentence_index=-1,
    )
    assert (
        vt_runtime.record_sentence_progress(
            session, 0, scene_index=0, beat_index=1
        )
        is True
    )
    assert session.visual_teaching_sentence_index == 0
    assert (
        vt_runtime.record_sentence_progress(
            session, 0, scene_index=0, beat_index=1
        )
        is False
    )
    assert (
        vt_runtime.record_sentence_progress(
            session, 2, scene_index=0, beat_index=1
        )
        is True
    )
    assert session.visual_teaching_sentence_index == 2


def test_sentence_progress_requires_matching_scene_beat():
    session = SimpleNamespace(
        visual_teaching_status="playing",
        visual_teaching_scene_index=1,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=-1,
    )
    # Missing identity rejected.
    assert vt_runtime.record_sentence_progress(session, 0) is False
    assert session.visual_teaching_sentence_index == -1
    # Wrong scene rejected.
    assert (
        vt_runtime.record_sentence_progress(
            session, 0, scene_index=0, beat_index=0
        )
        is False
    )
    assert session.visual_teaching_sentence_index == -1
    # Matching accepted.
    assert (
        vt_runtime.record_sentence_progress(
            session, 0, scene_index=1, beat_index=0
        )
        is True
    )
    assert session.visual_teaching_sentence_index == 0


def test_delayed_previous_beat_sentence_ignored():
    session = SimpleNamespace(
        visual_teaching_status="playing",
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=1,
        visual_teaching_sentence_index=0,
    )
    assert (
        vt_runtime.record_sentence_progress(
            session, 3, scene_index=0, beat_index=0
        )
        is False
    )
    assert session.visual_teaching_sentence_index == 0


def test_parse_sentence_action_requires_scene_beat_sentence():
    assert vt_runtime.parse_sentence_action("visual_teaching_sentence:1:2:3") == (
        1,
        2,
        3,
    )
    assert vt_runtime.parse_sentence_action("visual_teaching_sentence:3") is None
    assert vt_runtime.parse_sentence_action("visual_teaching_sentence") is None


def test_visual_state_at_restore():
    beat = VisualTeachingBeat(
        id="b1",
        visual_state=VisualState(highlights=["a"]),
        speak="One. Two.",
        sentence_events=[
            SemanticAnchorEvent(sentence_index=0, patch={"highlights": ["b"]}),
            SemanticAnchorEvent(sentence_index=1, patch={"pointer": "b"}),
        ],
    )
    assert visual_state_at(beat, sentence_index=-1).highlights == ["a"]
    assert visual_state_at(beat, sentence_index=0).highlights == ["b"]
    assert visual_state_at(beat, sentence_index=1).pointer == "b"


@pytest.mark.asyncio
async def test_duplicate_done_is_noop():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = SimpleNamespace(
        flow_state="concept_visual_teaching",
        visual_teaching_status="done",
        visual_teaching_plan={"scenes": []},
        concept_teaching_sequence_snapshot=["vtse", "visual_teaching"],
        concept_teaching_stage_index=2,
        current_zone=1,
        zone0_phase="done",
        concept_teaching_await_vtse_done=False,
    )
    result = await orch.maybe_emit(session, action="visual_teaching_done")
    assert result == {"type": "noop"}


@pytest.mark.asyncio
async def test_missing_binary_skips_scene():
    session = SimpleNamespace(
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=-1,
        visual_teaching_skipped_scenes=[],
        visual_teaching_status="playing",
    )
    plan = vt_runtime.VisualTeachingPlan.model_validate(
        {
            "scenes": [
                {
                    "asset_key": "gone",
                    "beats": [{"id": "b1", "speak": "A.", "visual_state": {}}],
                },
                {
                    "asset_key": "ok",
                    "beats": [{"id": "b1", "speak": "B.", "visual_state": {}}],
                },
            ]
        }
    )
    authored = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="gone",
                storage_key="gone.jpg",
                teaching_purpose="x",
            ),
            VisualTeachingImage(
                id="2",
                asset_key="ok",
                storage_key="ok.jpg",
                teaching_purpose="y",
            ),
        ]
    )

    async def exists(key: str) -> bool:
        return key == "ok.jpg"

    fake_storage = SimpleNamespace(exists=exists)
    with patch(
        "app.services.visual_teaching.runtime.get_visual_teaching_storage",
        return_value=fake_storage,
    ):
        ok = await vt_runtime.skip_to_next_playable_scene(
            session, plan, authored_snapshot=authored, concept_id="c1"
        )
    assert ok is True
    assert session.visual_teaching_scene_index == 1
    assert 0 in session.visual_teaching_skipped_scenes


@pytest.mark.asyncio
async def test_missing_all_binaries_exhausts():
    session = SimpleNamespace(
        visual_teaching_scene_index=0,
        visual_teaching_beat_index=0,
        visual_teaching_sentence_index=-1,
        visual_teaching_skipped_scenes=[],
        visual_teaching_status="playing",
    )
    plan = vt_runtime.VisualTeachingPlan.model_validate(
        {
            "scenes": [
                {
                    "asset_key": "gone",
                    "beats": [{"id": "b1", "speak": "A.", "visual_state": {}}],
                },
            ]
        }
    )
    authored = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="gone",
                storage_key="gone.jpg",
                teaching_purpose="x",
            ),
        ]
    )

    async def exists(_key: str) -> bool:
        return False

    with patch(
        "app.services.visual_teaching.runtime.get_visual_teaching_storage",
        return_value=SimpleNamespace(exists=exists),
    ):
        ok = await vt_runtime.skip_to_next_playable_scene(
            session, plan, authored_snapshot=authored, concept_id="c1"
        )
    assert ok is False
