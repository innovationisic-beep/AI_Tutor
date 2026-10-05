"""Hierarchy Phase B — layout contract, tree topology, role separation."""

from __future__ import annotations

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.semantic_extract import extract_authoring_semantics
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.strategies.clustered_trait_list import (
    build_clustered_trait_list_plan,
    build_clustered_trait_list_plan_flat,
)
from app.vtse.strategies.hierarchy_layout import hierarchy_node_parts


def _living_steps() -> list[dict]:
    return [
        {
            "title": "Living Things",
            "annotation": "Living things share core life processes.",
            "narration": "Let us anchor the idea first.",
        },
        {
            "title": "Grow",
            "annotation": "Living things increase in size over time.",
            "narration": "They grow over time.",
        },
        {
            "title": "Breathe",
            "annotation": "Living things exchange gases for energy.",
            "narration": "They breathe.",
        },
        {
            "title": "Reproduce",
            "annotation": "Living things can make new organisms.",
            "narration": "They reproduce.",
        },
    ]


def test_hierarchy_layout_hints_not_grouped_clusters() -> None:
    semantic = extract_authoring_semantics(
        topic_name="Living Things",
        concept="life",
        trait_steps=_living_steps(),
        source="template_steps",
    )
    plan = build_clustered_trait_list_plan_flat(
        topic_label=semantic.topic_label,
        traits=semantic.traits,
    )
    hints = plan.semantic_graph.layout_hints or {}
    assert hints.get("grouping") != "clustered"
    assert hints.get("preferred_layout") == "hierarchy_root_children"
    assert hints.get("topology_type") == "root_to_children"

    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    assert validate_cir_v1(cir).ok
    relations = {e["relation"] for e in cir["edges"]}
    assert "leads_to" not in relations
    assert relations == {"part_of"}

    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="s",
        topic_id="t",
        concept="life",
        planner=TimelinePlannerV3(),
    )
    lm = out.timeline.get("layout_metadata") or {}
    assert lm.get("layout_profile") == "hierarchy_root_children"
    assert lm.get("layout_mode") == "hierarchy_root_children"
    dbg = out.cir_instruction_debug or {}
    assert dbg.get("hierarchy_layout_contract")
    assert dbg.get("hierarchy_topology_type") == "root_to_children"
    assert dbg.get("hierarchy_sibling_chain_edges") == 0


def test_anchor_plus_traits_tree_edges_only() -> None:
    draft = extract_authoring_semantics(
        topic_name="Biology",
        concept="Cells",
        rag_context="- Membrane\n- DNA\n- Divide",
    )
    plan = build_clustered_trait_list_plan(draft)
    edges = plan.semantic_graph.edges
    assert all(e.relation == "part_of" for e in edges)
    assert all(e.from_id == "node_1" for e in edges)
    assert len(edges) == len(draft.traits)

    for node in plan.semantic_graph.nodes:
        identity, explanation = hierarchy_node_parts(node.label, node.summary)
        assert len(identity.split()) <= 6
        assert node.label == identity


def test_hierarchy_node_semantic_on_compile() -> None:
    semantic = extract_authoring_semantics(
        topic_name="Living Things",
        concept="life",
        trait_steps=_living_steps(),
    )
    plan = build_clustered_trait_list_plan_flat(
        topic_label=semantic.topic_label,
        traits=semantic.traits,
    )
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="s",
        topic_id=None,
        concept="life",
        planner=TimelinePlannerV3(),
    )
    first_ops = out.timeline["beats"][1]["operations"]
    add = next(o for o in first_ops if o["op_type"] == "add_entity")
    payload = add["payload"]["entity"]["semantic"]["payload"]
    assert payload.get("hierarchy_identity") == "Grow"
    assert "increase in size" in (payload.get("hierarchy_explanation") or "")
