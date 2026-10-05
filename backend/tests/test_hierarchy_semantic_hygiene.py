"""Hierarchy Phase A — semantic extraction hygiene tests."""

from __future__ import annotations

from app.vtse.authoring.hierarchy_semantic_hygiene import (
    classify_excluded_authoring_line,
    trait_overlaps_anchor,
)
from app.vtse.authoring.semantic_extract import TraitDraft, extract_authoring_semantics
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.selectors.strategy_selector import STRATEGY_CLUSTERED


def test_filters_placeholder_and_practice_rag_lines() -> None:
    rag = "\n".join(
        [
            "[Detailed — concept: living things]",
            "[Practice Question - For Reference Only]",
            "- Living things grow and develop over time",
            "- Living things exchange gases during respiration",
            "- Living things reproduce to create offspring",
        ],
    )
    draft = extract_authoring_semantics(
        topic_name="Biology",
        concept="Living Things",
        rag_context=rag,
    )
    labels = {t.label.lower() for t in draft.traits}
    assert "[detailed" not in " ".join(labels)
    assert "practice question" not in " ".join(labels)
    assert draft.hierarchy_hygiene is not None
    assert draft.hierarchy_hygiene.hierarchy_placeholder_filtered >= 1
    assert draft.hierarchy_hygiene.hierarchy_practice_nodes_filtered >= 1
    assert len(draft.traits) >= 3


def test_anchor_not_duplicated_as_first_trait() -> None:
    steps = [
        {
            "title": "Living Things",
            "annotation": "Living things share core life processes.",
            "narration": "Living things are organisms that share key life processes.",
        },
        {"title": "Grow", "annotation": "They grow.", "narration": "They grow over time."},
        {"title": "Breathe", "annotation": "They breathe.", "narration": "They exchange gases."},
        {"title": "Reproduce", "annotation": "They reproduce.", "narration": "They make offspring."},
    ]
    draft = extract_authoring_semantics(
        topic_name="Living Things",
        concept="Living Things",
        trait_steps=steps,
        source="template_steps",
    )
    assert draft.anchor_label == "Living Things"
    trait_labels = [t.label for t in draft.traits]
    assert "Living Things" not in trait_labels
    assert draft.hierarchy_hygiene is not None
    assert draft.hierarchy_hygiene.hierarchy_duplicate_nodes_removed >= 1


def test_trait_overlaps_anchor_prefix() -> None:
    trait = TraitDraft(
        label="Grow",
        summary="Living things are things that grow and develop.",
        narration="Living things grow over time.",
    )
    assert trait_overlaps_anchor(
        trait,
        anchor_label="Living Things",
        concept_label="Living Things",
    ) is False

    dup = TraitDraft(
        label="Living Things",
        summary="Living things are organisms with life processes.",
        narration="Living things share common traits.",
    )
    assert trait_overlaps_anchor(
        dup,
        anchor_label="Living Things",
        concept_label="Living Things",
    ) is True


def test_hierarchy_debug_in_plan_provenance() -> None:
    ctx = build_authoring_context(
        topic_name="Biology",
        concept="Living Things",
        rag_context="- Grow over time\n- Breathe\n- Reproduce",
    )
    plan, sel = build_teaching_plan(
        ctx,
        session_id="s1",
        topic_id="t1",
        concept="Living Things",
        forced_strategy_id=STRATEGY_CLUSTERED,
    )
    assert sel.strategy_id == STRATEGY_CLUSTERED
    assert "hierarchy_extraction" in plan.provenance
    assert plan.provenance["hierarchy_extraction"]["hierarchy_final_trait_count"] >= 2
    assert len(plan.semantic_graph.nodes) >= 3


def test_classify_scaffold_header() -> None:
    assert classify_excluded_authoring_line("[Detailed — concept: living things]") == "scaffold"
