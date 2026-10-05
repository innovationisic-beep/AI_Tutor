"""VTSE Phase 1 — infrastructure shell tests."""

from __future__ import annotations

from app.cir.examples_photosynthesis import photosynthesis_cir_v1
from app.cir.validate import validate_cir_v1
from app.vtse.compiler.cir_bridge import teaching_plan_from_cir_dict
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.flags import vtse_authoring_zone1_enabled, vtse_enabled, vtse_zone1_enabled
from app.vtse.pipeline import apply_vtse_shell_to_cir_dict, stamp_timeline_vtse_metadata
from app.vtse.registry.strategy_registry import (
    STRATEGY_IDS,
    get_strategy,
    list_strategies,
    resolve_strategy_id_for_representation,
)


def test_vtse_product_path_always_enabled() -> None:
    assert vtse_enabled() is True
    assert vtse_zone1_enabled() is True
    assert vtse_authoring_zone1_enabled() is True


def test_strategy_registry_complete() -> None:
    assert len(list_strategies()) == len(STRATEGY_IDS)
    for sid in STRATEGY_IDS:
        s = get_strategy(sid)
        assert s.strategy_id == sid
        assert s.layout_family


def test_resolve_strategy_deterministic() -> None:
    assert resolve_strategy_id_for_representation("cycle") == "cycle_process"
    assert resolve_strategy_id_for_representation("comparison") == "comparison_contrast"
    assert (
        resolve_strategy_id_for_representation(
            "hierarchy",
            layout_hints={"grouping": "clustered"},
            node_count=5,
        )
        == "clustered_trait_list"
    )


def test_cir_round_trip_photosynthesis() -> None:
    v = validate_cir_v1(photosynthesis_cir_v1())
    assert v.ok and v.cir is not None
    dumped = v.cir.model_dump(mode="json", by_alias=True)
    plan = teaching_plan_from_cir_dict(dumped)
    out = VTSECompiler().compile_to_cir_dict(plan).cir
    v2 = validate_cir_v1(out)
    assert v2.ok, v2.errors
    assert out["representation_type"] == dumped["representation_type"]
    assert len(out["nodes"]) == len(dumped["nodes"])
    assert len(out["beats"]) == len(dumped["beats"])


def test_shell_pass_through_always_on() -> None:
    raw = photosynthesis_cir_v1()
    v = validate_cir_v1(raw)
    assert v.ok
    out, obs = apply_vtse_shell_to_cir_dict(raw, session_id="sess_test")
    assert obs is not None
    assert obs["vtse_enabled"] is True
    assert obs["strategy_id"] in STRATEGY_IDS
    v2 = validate_cir_v1(out)
    assert v2.ok, v2.errors


def test_stamp_timeline_metadata() -> None:
    tl: dict = {
        "timeline_id": "tlm_x",
        "beats": [
            {"beat_id": "beat_1", "metadata": {}},
            {"beat_id": "beat_2", "metadata": {}},
        ],
        "metadata": {},
    }
    stamp_timeline_vtse_metadata(
        tl,
        {
            "vtse_enabled": True,
            "tdsl_version": "0.1",
            "strategy_id": "hierarchy_concept_intro",
            "plan_id": "plan_abc",
            "compiler_path": "teaching_plan_to_cir_v1",
            "compiler_version": "vtse-compiler-1.0.0",
            "pedagogical_roles": {"beat_1": "anchor", "beat_2": "explain"},
        },
    )
    assert tl["metadata"]["vtse"]["strategy_id"] == "hierarchy_concept_intro"
    assert tl["beats"][0]["metadata"]["pedagogical_role"] == "anchor"
