"""VTSE visual package: slots, stamp, publish, clone, and freeze."""

from __future__ import annotations

import copy
import inspect
from types import SimpleNamespace

import pytest

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.curriculum.concept_teaching_sequence import (
    teaching_sequence_auto_fingerprint,
)
from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
    ValidationResult,
)
from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)
from app.services.storage.visual_teaching_storage import set_vtse_visuals_storage
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.services.vtse_visuals.authored import (
    apply_vtse_visual_replace_stale,
    frozen_vtse_visuals,
    normalize_vtse_visuals,
)
from app.services.vtse_visuals.slots import iter_vtse_slots, resolve_binding, step_slot_key
from app.services.vtse_visuals.stamp import (
    comparison_cue_boundary,
    safe_attach_vtse_visuals,
)
from app.vtse.authoring.comparison_rows import ComparisonRow, teacher_pair_narration
from app.vtse.authoring.semantic_extract import TraitDraft
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.pipeline import build_vtse_observability, stamp_timeline_vtse_metadata
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
from app.vtse.strategies.linear_process import build_linear_process_plan


def _image(asset: str, storage: str, regions: list, status: str = "confirmed") -> dict:
    return {
        "id": "img1",
        "asset_key": asset,
        "storage_key": storage,
        "mime_type": "image/png",
        "natural_width": 400,
        "natural_height": 300,
        "content_hash": "abc",
        "annotations_status": status,
        "regions": regions,
        "anchors": [],
        "connections": [],
    }


def _region(region_id: str, binding: dict) -> dict:
    return {
        "region_id": region_id,
        "label": region_id,
        "shape": "rect",
        "geometry": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        "bindings": [binding],
    }


def _compile(plan) -> dict:
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    checked = validate_cir_v1(cir)
    assert checked.ok, checked.errors
    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="sess_vtse_visual",
        topic_id="topic_vtse_visual",
        concept=plan.concept_id or "concept",
        planner=TimelinePlannerV3(),
    )
    return out.timeline


def _obs(plan) -> dict:
    compiled = VTSECompiler().compile_to_cir_dict(plan)
    return build_vtse_observability(
        plan=plan,
        compile_result=compiled,
        authoring_source="test",
        compiler_path="teaching_plan_to_cir_v1",
    )


def _linear_plan():
    return build_linear_process_plan(
        topic_label="Mixing",
        steps=(
            TraitDraft(label="Gather", summary="Get tools", narration="Gather the tools."),
            TraitDraft(label="Mix", summary="First mix", narration="Mix the first batch."),
            TraitDraft(label="Mix", summary="Second mix", narration="Mix the second batch."),
        ),
        concept_id="concept_mix",
    )


def _binding(key: str, index: int, side: str = "") -> dict:
    kind = key.split(":", 1)[0]
    return {
        "slot_kind": kind,
        "slot_key": key,
        "slot_index": index,
        "side": side,
    }


def test_missing_package_leaves_beats_unchanged() -> None:
    plan = _linear_plan()
    timeline = _compile(plan)
    before = copy.deepcopy(timeline["beats"])
    stamp_timeline_vtse_metadata(timeline, _obs(plan))
    assert [b["beat_id"] for b in timeline["beats"]] == [b["beat_id"] for b in before]
    assert [b["operations"] for b in timeline["beats"]] == [b["operations"] for b in before]
    assert [b["narration_segments"] for b in timeline["beats"]] == [
        b["narration_segments"] for b in before
    ]
    assert all("vtse_visual" not in (b.get("metadata") or {}) for b in timeline["beats"])
    assert "vtse_visual_package" not in (timeline.get("metadata") or {})


def test_bound_region_stamps_only_matching_beat() -> None:
    plan = _linear_plan()
    timeline = _compile(plan)
    key = step_slot_key("Mix")
    package = {
        "images": [
            _image(
                "diagram",
                "abc/diagram.png",
                [_region("r1", _binding(key, 1))],
            )
        ]
    }
    stamp_timeline_vtse_metadata(
        timeline,
        _obs(plan),
        vtse_visuals=package,
        concept_id="concept_mix",
    )
    stamped = [
        b["beat_id"]
        for b in timeline["beats"]
        if (b.get("metadata") or {}).get("vtse_visual")
    ]
    assert stamped == ["beat_0001"]
    visual = timeline["beats"][1]["metadata"]["vtse_visual"]
    assert visual["region_ids"] == ["r1"]
    assert "storage_key" not in timeline["metadata"]["vtse_visual_package"]["images"][0]
    again = copy.deepcopy(timeline)
    stamp_timeline_vtse_metadata(
        again, _obs(plan), vtse_visuals=package, concept_id="concept_mix"
    )
    assert again["beats"][1]["metadata"]["vtse_visual"] == visual


def test_duplicate_titles_use_slot_index() -> None:
    slots = iter_vtse_slots(
        {
            "strategy_id": "linear_process",
            "payload": {"steps": [{"label": "Mix"}, {"label": "Mix"}]},
        }
    )
    first = resolve_binding(_binding(step_slot_key("Mix"), 0), slots)
    second = resolve_binding(_binding(step_slot_key("Mix"), 1), slots)
    assert len(first) == 1 and first[0]["slot_index"] == 0
    assert len(second) == 1 and second[0]["slot_index"] == 1


def test_publish_gates() -> None:
    service = CurriculumValidationService()
    template = {
        "strategy_id": "linear_process",
        "payload": {"steps": [{"label": "Gather"}, {"label": "Mix"}, {"label": "Serve"}]},
    }

    def check(images):
        result = ValidationResult()
        service._check_vtse_visuals(
            result,
            concept={
                "display_name": "Mixing",
                "vtse_template": template,
                "vtse_visuals": {"images": images} if images is not None else None,
            },
            concept_name="Mixing",
            concept_path="concepts/mixing",
        )
        return result

    empty = check(None)
    assert empty.errors == [] and empty.warnings == []
    key = step_slot_key("Mix")
    ok = check([_image("diagram", "abc/diagram.png", [_region("r1", _binding(key, 1))])])
    assert ok.errors == []
    unknown = check(
        [_image("diagram", "abc/diagram.png", [_region("r1", _binding("step:missing", 0))])]
    )
    assert any(e.code == "VTSE_VISUAL_UNBOUND_SLOT" for e in unknown.errors)
    stale = check(
        [
            _image(
                "diagram",
                "abc/diagram.png",
                [_region("r1", _binding(key, 1))],
                status="stale",
            )
        ]
    )
    assert any(e.code == "VTSE_VISUAL_STALE_ANNOTATIONS" for e in stale.errors)
    bad = check(
        [
            _image(
                "diagram",
                "abc/diagram.png",
                [
                    {
                        "region_id": "r1",
                        "shape": "rect",
                        "geometry": {"x": 2, "y": 0, "w": 0.2, "h": 0.2},
                        "bindings": [_binding(key, 1)],
                    }
                ],
            )
        ]
    )
    assert any(e.code == "VTSE_VISUAL_INVALID_GEOMETRY" for e in bad.errors)
    missing = check([_image("diagram", "", [_region("r1", _binding(key, 1))])])
    assert any(e.code == "VTSE_VISUAL_MISSING_STORAGE" for e in missing.errors)
    unbound = check([_image("diagram", "abc/diagram.png", [])])
    assert unbound.errors == []
    assert any(w.code == "VTSE_VISUAL_IMAGE_NO_REGIONS" for w in unbound.warnings)


def test_fingerprint_ignores_vtse_visuals() -> None:
    base = SimpleNamespace(
        teaching_sequence=["vtse"],
        teaching_sequence_mode="manual",
        study_points=["a"],
        learning_outcomes=["b"],
        story_hook=None,
        visual_teaching=None,
        vtse_template={"strategy_id": "linear_process", "payload": {}},
        vtse_visuals=None,
    )
    other = SimpleNamespace(**{**base.__dict__, "vtse_visuals": {"images": [{"asset_key": "x"}]}})
    assert teaching_sequence_auto_fingerprint(base) == teaching_sequence_auto_fingerprint(other)


def test_replace_forces_stale_until_reconfirm() -> None:
    previous = {"images": [_image("diagram", "abc/one.png", [])]}
    replaced = apply_vtse_visual_replace_stale(
        previous,
        {"images": [_image("diagram", "abc/two.png", [], status="confirmed")]},
    )
    assert replaced["images"][0]["annotations_status"] == "stale"
    same = apply_vtse_visual_replace_stale(
        previous,
        {"images": [_image("diagram", "abc/one.png", [], status="confirmed")]},
    )
    assert same["images"][0]["annotations_status"] == "confirmed"


def test_comparison_cues_follow_the_spoken_clause() -> None:
    left = "pores stay closed"
    right = "pores open wide"
    spoken = teacher_pair_narration(
        dimension="Water",
        left_label="Night",
        right_label="Day",
        left_detail=left,
        right_detail=right,
    )
    boundary = comparison_cue_boundary(spoken, left_detail=left, right_detail=right)
    assert boundary == spoken.find("pores open wide")
    marker = "When we compare Night and Day, one side. In contrast, the other side."
    assert comparison_cue_boundary(marker, left_detail="absent", right_detail="missing") == marker.find(
        "In contrast, "
    )
    custom = "Night and day differ in a way this sentence never splits."
    assert comparison_cue_boundary(custom, left_detail=left, right_detail=right) is None

    plan = build_comparison_contrast_plan(
        topic_label="Stomata",
        sides=ComparisonSidesDraft(
            left_label="Night",
            right_label="Day",
            rows=(
                ComparisonRow(
                    dimension="Water",
                    left_title="Closed",
                    left_detail=left,
                    right_title="Open",
                    right_detail=right,
                ),
            ),
        ),
        concept_id="concept_stoma",
    )
    timeline = _compile(plan)
    package = {
        "images": [
            _image(
                "diagram",
                "abc/diagram.png",
                [
                    _region("left", _binding("row:water", 0, "left")),
                    _region("right", _binding("row:water", 0, "right")),
                    _region("shared", _binding("row:water", 0, "both")),
                ],
            )
        ]
    }
    stamp_timeline_vtse_metadata(
        timeline, _obs(plan), vtse_visuals=package, concept_id="concept_stoma"
    )
    visuals = [(b.get("metadata") or {}).get("vtse_visual") for b in timeline["beats"]]
    owner = next(v for v in visuals if v and v.get("cues"))
    assert owner["cues"][0]["char_start"] == 0
    assert "left" in owner["cues"][0]["region_ids"]
    assert "shared" in owner["cues"][0]["region_ids"]
    assert "right" not in owner["cues"][0]["region_ids"]
    assert owner["cues"][1]["char_start"] == boundary
    assert "right" in owner["cues"][1]["region_ids"]
    assert "shared" in owner["cues"][1]["region_ids"]
    carry = [v for v in visuals if v and v.get("carry")]
    assert carry == [{"carry": True}]


def test_custom_pair_narration_highlights_the_whole_row() -> None:
    plan = build_comparison_contrast_plan(
        topic_label="Stomata",
        sides=ComparisonSidesDraft(
            left_label="Night",
            right_label="Day",
            rows=(
                ComparisonRow(
                    dimension="Water",
                    left_title="Closed",
                    left_detail="pores stay closed",
                    right_title="Open",
                    right_detail="pores open wide",
                    pair_narration_text="Night and day differ here.",
                ),
            ),
        ),
    )
    timeline = _compile(plan)
    package = {
        "images": [
            _image(
                "diagram",
                "abc/diagram.png",
                [
                    _region("left", _binding("row:water", 0, "left")),
                    _region("right", _binding("row:water", 0, "right")),
                ],
            )
        ]
    }
    stamp_timeline_vtse_metadata(timeline, _obs(plan), vtse_visuals=package, concept_id="c1")
    owner = next(
        (b.get("metadata") or {}).get("vtse_visual")
        for b in timeline["beats"]
        if (b.get("metadata") or {}).get("vtse_visual", {}).get("cues")
    )
    assert len(owner["cues"]) == 1
    assert set(owner["cues"][0]["region_ids"]) == {"left", "right"}


def test_stamp_failure_omits_metadata_and_keeps_the_timeline() -> None:
    import app.services.vtse_visuals.stamp as stamp_mod

    timeline = {"beats": [{"beat_id": "beat_0000", "metadata": {}}], "metadata": {}}
    original = stamp_mod.attach_vtse_visuals

    def boom(*_a, **_k):
        raise RuntimeError("diagram")

    stamp_mod.attach_vtse_visuals = boom
    try:
        safe_attach_vtse_visuals(
            timeline,
            slots_by_beat={
                "beat_0000": {
                    "slot_kind": "step",
                    "slot_key": "step:mix",
                    "slot_index": 0,
                }
            },
            package={
                "images": [
                    _image(
                        "diagram",
                        "abc/diagram.png",
                        [_region("r", _binding("step:mix", 0))],
                    )
                ]
            },
            concept_id="c1",
        )
    finally:
        stamp_mod.attach_vtse_visuals = original
    assert "vtse_visual" not in timeline["beats"][0]["metadata"]
    assert "vtse_visual_package" not in timeline["metadata"]


@pytest.mark.asyncio
async def test_clone_copies_bytes_and_keeps_the_source_key() -> None:
    class Storage:
        def __init__(self) -> None:
            self.copied: list[str] = []

        async def copy(self, source_key: str, *, key_hint: str | None = None) -> str:
            self.copied.append(source_key)
            return f"cloned/{source_key}"

        async def delete(self, storage_key: str) -> None:
            return None

    storage = Storage()
    set_vtse_visuals_storage(storage)
    source = SimpleNamespace(
        id="src",
        vtse_visuals={
            "images": [
                _image(
                    "diagram",
                    "abc/diagram.png",
                    [_region("r1", _binding("step:mix", 0))],
                )
            ]
        },
    )
    from app.services.curriculum.curriculum_clone_service import CurriculumCloneService

    pkgs, copied, written = await CurriculumCloneService()._duplicate_vtse_visuals([source])
    assert copied == 1
    assert storage.copied == ["abc/diagram.png"]
    assert source.vtse_visuals["images"][0]["storage_key"] == "abc/diagram.png"
    cloned = pkgs["src"]["images"][0]
    assert cloned["storage_key"] == "cloned/abc/diagram.png"
    assert cloned["regions"][0]["region_id"] == "r1"
    assert cloned["regions"][0]["bindings"][0]["slot_key"] == "step:mix"
    assert written == ["cloned/abc/diagram.png"]
    set_vtse_visuals_storage(None)


@pytest.mark.asyncio
async def test_second_snapshot_keeps_the_frozen_package() -> None:
    session = SimpleNamespace(
        current_concept_index=0,
        concept_teaching_for_index=0,
        concept_teaching_sequence_snapshot=["vtse"],
        concept_teaching_vtse_visuals_snapshot={"images": [{"asset_key": "kept"}]},
    )
    seq = await ConceptTeachingOrchestrator(concept_repo=object()).ensure_sequence_snapshot(session)  # type: ignore[arg-type]
    assert seq == ["vtse"]
    assert session.concept_teaching_vtse_visuals_snapshot["images"][0]["asset_key"] == "kept"


def test_curriculum_edit_after_freeze_does_not_replace_the_package() -> None:
    session = SimpleNamespace(
        current_concept_index=0,
        concept_teaching_for_index=0,
        concept_teaching_vtse_visuals_snapshot={"images": [{"asset_key": "frozen"}]},
    )
    live = {"images": [{"asset_key": "edited"}]}
    assert frozen_vtse_visuals(session, live)["images"][0]["asset_key"] == "frozen"
    unfrozen = SimpleNamespace(current_concept_index=0, concept_teaching_for_index=-1)
    assert frozen_vtse_visuals(unfrozen, live)["images"][0]["asset_key"] == "edited"


def test_reteach_does_not_read_vtse_visuals() -> None:
    from app.services.handlers import cluster_teachback_orchestrator as mod

    source = inspect.getsource(mod._run_simplified_vtse_reteach)
    assert "vtse_visual" not in source


def test_normalize_empty_package_is_absent() -> None:
    assert normalize_vtse_visuals(None) is None
    assert normalize_vtse_visuals({"images": []}) is None
