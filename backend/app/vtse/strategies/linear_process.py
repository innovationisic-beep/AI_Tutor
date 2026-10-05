"""linear_process — vertical process storyboard (identity node + explanation panel)."""

from __future__ import annotations

from app.cir.limits import CIR_V1_MAX_NODES, ROW_NARRATION_MAX
from app.vtse.authoring.content_filters import sanitize_process_production_text
from app.vtse.authoring.process_step_content import split_process_step_content
from app.vtse.authoring.process_step_schema import (
    ProcessAuthoringMeta,
    process_authoring_meta_to_dict,
)
from app.vtse.authoring.process_steps import ProcessStepExtractionStats
from app.vtse.authoring.semantic_extract import TraitDraft
from app.vtse.models.plan import (
    InteractionPolicy,
    PedagogicalRole,
    SemanticEdge,
    SemanticGraph,
    SemanticNode,
    TeachingPlan,
    TeachingStrategyRef,
)
from app.vtse.registry.strategy_registry import get_strategy
from app.services.vtse_visuals.slots import make_vtse_slot, step_slot_key
from app.vtse.strategies.common import make_beat, node_id, stable_plan_id

STRATEGY_ID = "linear_process"
_AUTHORING_SOURCE = "vtse_linear_process_storyboard_v1"
PROCESS_MIN_STEPS = 3
PROCESS_MAX_STEPS = CIR_V1_MAX_NODES


def _role_for_linear_index(index: int, total: int) -> PedagogicalRole:
    if index == 0:
        return "anchor"
    if index == total - 1:
        return "close"
    return "explain" if index % 2 == 1 else "reinforce"


def _storyboard_parts(step: TraitDraft, index: int) -> tuple[str, str, str]:
    """Return (step_display_label, identity, explanation)."""
    combined = step.summary or step.label or ""
    display, identity, explanation = split_process_step_content(combined, index=index)
    identity = sanitize_process_production_text(step.label or identity, fallback=identity, max_len=80)
    explanation = sanitize_process_production_text(
        step.summary or explanation,
        fallback=explanation,
        max_len=600,
    )
    if explanation.strip().lower() == identity.strip().lower():
        explanation = sanitize_process_production_text(
            step.narration or explanation,
            fallback=explanation,
            max_len=600,
        )
    return display, identity, explanation


def build_linear_process_plan(
    *,
    topic_label: str,
    steps: tuple[TraitDraft, ...],
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    authoring_source: str = _AUTHORING_SOURCE,
    extraction_stats: ProcessStepExtractionStats | None = None,
    process_authoring_meta: ProcessAuthoringMeta | None = None,
) -> TeachingPlan:
    strat = get_strategy(STRATEGY_ID)
    n = len(steps)
    if n < PROCESS_MIN_STEPS or n > PROCESS_MAX_STEPS:
        raise ValueError(
            f"linear_process requires {PROCESS_MIN_STEPS}–{PROCESS_MAX_STEPS} steps, got {n}",
        )

    nodes: list[SemanticNode] = []
    for i, step in enumerate(steps):
        step_display, identity, explanation = _storyboard_parts(step, i)
        narration = sanitize_process_production_text(
            step.narration,
            fallback=explanation,
            max_len=ROW_NARRATION_MAX,
        )
        nodes.append(
            SemanticNode(
                id=node_id(i),
                label=identity,
                summary=explanation,
                kind="process",
                semantic_role="process_step",
                group="sequence",
                preferred_position="flow",
                narration=narration,
            ),
        )

    edges: list[SemanticEdge] = []
    for i in range(1, n):
        edges.append(
            SemanticEdge(
                from_id=node_id(i - 1),
                to=node_id(i),
                relation="leads_to",
            ),
        )

    beats = []
    duplicate_suppressed = 0
    for i, step in enumerate(steps):
        nid = node_id(i)
        step_display, identity, explanation = _storyboard_parts(step, i)
        if explanation.strip().lower() == identity.strip().lower():
            duplicate_suppressed += 1
        beats.append(
            make_beat(
                index=i,
                focus_id=nid,
                role=_role_for_linear_index(i, n),
                narration=nodes[i].narration,
                annotation=explanation,
                highlight_ids=[nid],
                authoring_source=authoring_source,
                extra_metadata={
                    "sequence_index": i,
                    "process_scene_index": i,
                    "step_display_label": step_display,
                    "process_identity": identity,
                    "vtse_slot": make_vtse_slot(
                        slot_kind="step",
                        slot_key=step_slot_key(step.label),
                        slot_index=i,
                        label=step.label,
                    ),
                },
            ),
        )

    stats = extraction_stats or ProcessStepExtractionStats(
        process_step_count=n,
        process_scene_count=n,
    )
    process_debug = (
        process_authoring_meta_to_dict(process_authoring_meta)
        if process_authoring_meta is not None
        else {
            "process_authoring_mode": "deterministic",
            "renderer_contract_valid": True,
            "narration_richness_level": "deterministic_v1",
        }
    )
    key = topic_label + "|" + "|".join(s.label for s in steps)
    return TeachingPlan(
        plan_id=stable_plan_id("lin", key),
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id,
        learning_objective=topic_label,
        strategy=TeachingStrategyRef(
            strategy_id=STRATEGY_ID,
            strategy_version=strat.version,
            layout_family=strat.layout_family,
        ),
        interaction_policy=InteractionPolicy(),
        semantic_graph=SemanticGraph(
            representation_type="flow",
            topic=topic_label,
            nodes=nodes,
            edges=edges,
            layout_hints={
                "grouping": "sequence",
                "preferred_layout": "vertical_flow",
                "emphasis": "ordered_flow",
                "process_render_mode": "process_storyboard_lanes",
                "storyboard_lane_mode": "center_node_right_explanation",
            },
        ),
        beats=beats,
        provenance={
            "authoring_source": authoring_source,
            "semantic_shape": "linear_process",
            "process_authoring": process_debug,
            "plan_summary": {
                "mode": "linear_storyboard",
                "step_count": n,
                "step_labels": [s.label for s in steps],
                "process_storyboard": {
                    "filtered_placeholder_count": stats.filtered_placeholder_count,
                    "filtered_practice_nodes": stats.filtered_practice_nodes,
                    "process_step_count": stats.process_step_count,
                    "process_scene_count": stats.process_scene_count,
                    "rendered_process_steps": n,
                    "explanation_panel_count": n,
                    "storyboard_lane_mode": "center_node_right_explanation",
                    "duplicate_content_suppressed": duplicate_suppressed,
                    "dynamic_process_length": True,
                    "layout_mode": "vertical_process_phaseA",
                    "semantic_shape": "linear_process",
                },
            },
        },
    )
