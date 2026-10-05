"""VTSE Phase 2 — TeachingPlan authoring tests."""

from __future__ import annotations

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.semantic_extract import extract_authoring_semantics
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.strategies.clustered_trait_list import (
    STRATEGY_ID,
    build_clustered_trait_list_plan,
    build_clustered_trait_list_plan_flat,
)


def _living_things_steps() -> list[dict]:
    return [
        {
            "title": "Living Things",
            "annotation": "Living things share core life processes.",
            "narration": "Let us anchor the idea first: living things share a common set of life processes.",
        },
        {
            "title": "Grow",
            "annotation": "Living things increase in size over time.",
            "narration": "A core sign of living things is that they grow over time.",
        },
        {
            "title": "Breathe",
            "annotation": "Living things exchange gases for energy.",
            "narration": "Living things also breathe, exchanging gases to stay alive.",
        },
        {
            "title": "Reproduce",
            "annotation": "Living things can make new organisms.",
            "narration": "And living things reproduce to create new living organisms.",
        },
    ]


def test_clustered_trait_list_flat_living_things_golden() -> None:
    semantic = extract_authoring_semantics(
        topic_name="Living Things",
        concept="life processes",
        trait_steps=_living_things_steps(),
        source="template_steps",
    )
    plan = build_clustered_trait_list_plan_flat(
        topic_label=semantic.topic_label,
        traits=semantic.traits,
        concept_id="life processes",
    )
    assert plan.strategy.strategy_id == STRATEGY_ID
    assert len(plan.beats) == 4
    assert len(plan.semantic_graph.nodes) == 4
    assert plan.beats[0].pedagogical_role == "anchor"
    assert plan.beats[0].focus_node_id == "node_1"
    assert plan.beats[0].reveal_script is not None
    assert len(plan.beats[0].reveal_script.steps) >= 2

    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    v = validate_cir_v1(cir)
    assert v.ok, v.errors
    assert len(cir["beats"]) == len(cir["nodes"]) == 4
    assert cir["layout_hints"]["preferred_layout"] == "hierarchy_root_children"
    assert cir["layout_hints"].get("grouping") != "clustered"

    result = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="sess_golden",
        topic_id="topic_lt",
        concept="life processes",
        planner=TimelinePlannerV3(),
    )
    tl = result.timeline
    assert len(tl.get("beats") or []) == 4
    assert tl.get("layout_metadata", {}).get("layout_profile") == "hierarchy_root_children"


def test_anchor_plus_traits_deterministic_rag() -> None:
    semantic = extract_authoring_semantics(
        topic_name="Biology",
        concept="Cells",
        rag_context="- Cells have a membrane\n- Cells contain DNA\n- Cells divide",
    )
    plan = build_clustered_trait_list_plan(semantic)
    assert len(plan.semantic_graph.nodes) == 1 + len(semantic.traits)
    assert len(plan.beats) == len(plan.semantic_graph.nodes)
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    assert validate_cir_v1(cir).ok


def test_authoring_deterministic_repeatable() -> None:
    steps = _living_things_steps()
    p1 = build_clustered_trait_list_plan_flat(
        topic_label="Living Things",
        traits=extract_authoring_semantics(
            topic_name="Living Things",
            concept="life",
            trait_steps=steps,
        ).traits,
    )
    p2 = build_clustered_trait_list_plan_flat(
        topic_label="Living Things",
        traits=extract_authoring_semantics(
            topic_name="Living Things",
            concept="life",
            trait_steps=steps,
        ).traits,
    )
    assert p1.plan_id == p2.plan_id
    assert [b.narration_text for b in p1.beats] == [b.narration_text for b in p2.beats]
