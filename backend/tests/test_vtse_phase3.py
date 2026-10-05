"""VTSE Phase 3 — multi-strategy authoring golden tests (forced strategy path)."""

from __future__ import annotations

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.examples_photosynthesis import photosynthesis_cir_v1
from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.authoring.semantic_extract import TraitDraft
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.selectors.strategy_selector import (
    STRATEGY_COMPARISON,
    STRATEGY_CYCLE,
    STRATEGY_LINEAR,
    select_authoring_strategy,
)
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
from app.vtse.strategies.cycle_process import build_cycle_process_plan


def _compile_plan(plan) -> dict:
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    v = validate_cir_v1(cir)
    assert v.ok, v.errors
    assert len(cir["nodes"]) == len(cir["beats"])
    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="sess_p3",
        topic_id="topic_p3",
        concept=plan.concept_id or "concept",
        planner=TimelinePlannerV3(),
    )
    return out.timeline


def test_forced_strategy_comparison() -> None:
    ctx = build_authoring_context(
        topic_name="Living vs Non-Living",
        concept="life characteristics",
        force_shape="comparison",
    )
    sel = select_authoring_strategy(ctx, forced_strategy_id=STRATEGY_COMPARISON)
    assert sel.strategy_id == STRATEGY_COMPARISON
    assert sel.strategy_reason == "forced:vtse_template"
    assert sel.semantic_shape == "comparison"


def test_living_vs_non_living_comparison_golden() -> None:
    sides = ComparisonSidesDraft(
        left_label="Living",
        right_label="Non-Living",
        left_traits=(
            TraitDraft("Grows", "Living things grow.", "Living things grow over time."),
            TraitDraft("Reproduces", "Living things reproduce.", "Living things make offspring."),
            TraitDraft("Responds", "Living things respond.", "Living things respond to stimuli."),
        ),
        right_traits=(
            TraitDraft("No growth", "Non-living things do not grow.", "They do not grow on their own."),
            TraitDraft("No reproduction", "They do not reproduce.", "They do not create offspring."),
            TraitDraft("No response", "They do not respond.", "They do not sense and react."),
        ),
    )
    plan = build_comparison_contrast_plan(
        topic_label="Living vs Non-Living",
        sides=sides,
        concept_id="life",
    )
    assert plan.strategy.strategy_id == "comparison_contrast"
    assert len(plan.beats) == len(plan.semantic_graph.nodes)
    assert 6 <= len(plan.beats) <= 24
    assert plan.beats[0].pedagogical_role == "anchor"
    assert plan.beats[2].pedagogical_role == "compare"
    tl = _compile_plan(plan)
    lm = tl.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "comparison_split"
    assert lm.get("layout_mode") == "comparison_columns"


def test_plant_cell_vs_animal_cell_comparison() -> None:
    ctx = build_authoring_context(
        topic_name="Plant Cell vs Animal Cell",
        concept="cell structure",
        rag_context="- Chloroplasts in plant cells\n- Centrioles in animal cells\n- Cell wall in plants",
        force_shape="comparison",
    )
    plan, sel = build_teaching_plan(
        ctx,
        session_id="s",
        topic_id="t",
        concept="cells",
        forced_strategy_id=STRATEGY_COMPARISON,
    )
    assert sel.strategy_id == STRATEGY_COMPARISON
    assert len(plan.beats) >= 6
    tl = _compile_plan(plan)
    assert (tl.get("layout_metadata") or {}).get("layout_profile") == "comparison_split"


def test_water_cycle_golden() -> None:
    ctx = build_authoring_context(
        topic_name="Water Cycle",
        concept="hydrologic cycle",
        force_shape="cycle",
    )
    plan, sel = build_teaching_plan(
        ctx,
        session_id="s",
        topic_id="t",
        concept="water",
        forced_strategy_id=STRATEGY_CYCLE,
    )
    assert sel.strategy_id == STRATEGY_CYCLE
    assert plan.semantic_graph.representation_type == "cycle"
    assert len(plan.beats) == 4
    tl = _compile_plan(plan)
    lm = tl.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "cycle_ring"
    assert lm.get("layout_mode") == "cycle_radial"
    last_ops = tl["beats"][-1]["operations"]
    assert any(o.get("op_type") == "connect_entities" for o in last_ops)


def test_butterfly_life_cycle_golden() -> None:
    steps = (
        TraitDraft("Egg", "Starts as egg.", "The cycle begins with an egg.", "process"),
        TraitDraft("Larva", "Caterpillar stage.", "The larva feeds and grows.", "process"),
        TraitDraft("Pupa", "Chrysalis stage.", "Inside the pupa, transformation happens.", "process"),
        TraitDraft("Adult", "Butterfly emerges.", "The adult can reproduce.", "process"),
    )
    plan = build_cycle_process_plan(topic_label="Butterfly Life Cycle", steps=steps)
    assert len(plan.beats) == 4
    tl = _compile_plan(plan)
    assert (tl.get("layout_metadata") or {}).get("layout_profile") == "cycle_ring"


def test_digestion_linear_process_golden() -> None:
    ctx = build_authoring_context(
        topic_name="Digestion Process",
        concept="digestion",
        force_shape="linear_process",
    )
    plan, sel = build_teaching_plan(
        ctx,
        session_id="s",
        topic_id="t",
        concept="digestion",
        forced_strategy_id=STRATEGY_LINEAR,
    )
    assert sel.strategy_id == STRATEGY_LINEAR
    assert plan.semantic_graph.representation_type == "flow"
    tl = _compile_plan(plan)
    lm = tl.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "vertical_process_phaseA"
    assert lm.get("layout_mode") == "vertical_process_phaseA"
    assert lm.get("semantic_shape") == "linear_process"
    assert lm.get("process_step_count") >= 3


def test_photosynthesis_flow_linear() -> None:
    ctx = build_authoring_context(
        topic_name="Photosynthesis Flow",
        concept="photosynthesis",
        force_shape="linear_process",
    )
    sel = select_authoring_strategy(ctx, forced_strategy_id=STRATEGY_LINEAR)
    assert sel.strategy_id == STRATEGY_LINEAR
    plan, _ = build_teaching_plan(
        ctx,
        session_id="s",
        topic_id="t",
        concept="photosynthesis",
        forced_strategy_id=STRATEGY_LINEAR,
    )
    tl = _compile_plan(plan)
    lm = tl.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "vertical_process_phaseA"
    ref = photosynthesis_cir_v1()
    ref_out = compile_cir_v1_to_timeline(
        cir=ref,
        session_id="s",
        topic_id="t",
        concept="photosynthesis",
        planner=TimelinePlannerV3(),
    )
    assert len(tl["beats"]) == len(ref_out.timeline["beats"])


def test_multi_strategy_deterministic_replay() -> None:
    ctx1 = build_authoring_context(
        topic_name="Water Cycle",
        concept="water",
        force_shape="cycle",
    )
    p1, _ = build_teaching_plan(
        ctx1,
        session_id="a",
        topic_id="b",
        concept="water",
        forced_strategy_id=STRATEGY_CYCLE,
    )
    ctx2 = build_authoring_context(
        topic_name="Water Cycle",
        concept="water",
        force_shape="cycle",
    )
    p2, _ = build_teaching_plan(
        ctx2,
        session_id="a",
        topic_id="b",
        concept="water",
        forced_strategy_id=STRATEGY_CYCLE,
    )
    assert p1.plan_id == p2.plan_id
    assert [b.narration_text for b in p1.beats] == [b.narration_text for b in p2.beats]


def test_observability_metadata_on_plan() -> None:
    ctx = build_authoring_context(
        topic_name="Living vs Non-Living",
        concept="life",
        force_shape="comparison",
    )
    plan, sel = build_teaching_plan(
        ctx,
        session_id="s",
        topic_id="t",
        concept="life",
        forced_strategy_id=STRATEGY_COMPARISON,
    )
    summary = plan.provenance.get("plan_summary") or {}
    assert summary.get("selected_strategy") == sel.strategy_id
    assert summary.get("strategy_reason") == "forced:vtse_template"
    assert summary.get("semantic_shape") == "comparison"
    assert summary.get("beat_generation_summary")
