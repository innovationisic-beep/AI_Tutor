"""cycle_process — cyclic semantic graph and ring-compatible beats."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.vtse.authoring.semantic_extract import TraitDraft

if TYPE_CHECKING:
    from app.vtse.authoring.process_step_schema import ProcessAuthoringMeta, ProcessStepExtractionStats
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

STRATEGY_ID = "cycle_process"
_AUTHORING_SOURCE = "vtse_cycle_process_v1"


def _role_for_cycle_index(index: int, total: int) -> PedagogicalRole:
    if index == 0:
        return "anchor"
    if index == total - 1:
        return "close"
    if index == total - 2:
        return "reinforce"
    return "explain" if index % 2 == 1 else "reinforce"


def build_cycle_process_plan(
    *,
    topic_label: str,
    steps: tuple[TraitDraft, ...],
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    authoring_source: str = _AUTHORING_SOURCE,
    extraction_stats: "ProcessStepExtractionStats | None" = None,
    process_authoring_meta: "ProcessAuthoringMeta | None" = None,
) -> TeachingPlan:
    strat = get_strategy(STRATEGY_ID)
    n = len(steps)
    if n < 3 or n > 8:
        raise ValueError(f"cycle_process requires 3–8 steps, got {n}")

    nodes: list[SemanticNode] = []
    for i, step in enumerate(steps):
        nodes.append(
            SemanticNode(
                id=node_id(i),
                label=step.label,
                summary=step.summary,
                kind="process",
                semantic_role="cycle_stage",
                group="cycle",
                preferred_position="ring",
                narration=step.narration,
            ),
        )

    edges: list[SemanticEdge] = []
    for i in range(n):
        edges.append(
            SemanticEdge(
                from_id=node_id(i),
                to=node_id((i + 1) % n),
                relation="leads_to",
            ),
        )

    beats = []
    for i, step in enumerate(steps):
        nid = node_id(i)
        role = _role_for_cycle_index(i, n)
        beats.append(
            make_beat(
                index=i,
                focus_id=nid,
                role=role,
                narration=step.narration,
                annotation=step.summary,
                highlight_ids=[nid],
                authoring_source=authoring_source,
                extra_metadata={
                    "cycle_index": i,
                    "loop_closure": i == n - 1,
                    "vtse_slot": make_vtse_slot(
                        slot_kind="step",
                        slot_key=step_slot_key(step.label),
                        slot_index=i,
                        label=step.label,
                    ),
                },
            ),
        )

    key = topic_label + "|" + "|".join(s.label for s in steps)

    # Observability — mirrors linear_process pattern
    cycle_obs: dict[str, Any] = {
        "cycle_authoring_mode": "deterministic",
        "cycle_llm_consumed": False,
        "cycle_stage_count": n,
        "cycle_stage_labels": [s.label for s in steps],
        "cycle_explanation_count": sum(1 for s in steps if s.summary and len(s.summary) > 20),
        "cycle_overview_moved_to_narration": False,
    }
    if process_authoring_meta is not None:
        cycle_obs["cycle_authoring_mode"] = process_authoring_meta.process_authoring_mode
        cycle_obs["cycle_llm_consumed"] = process_authoring_meta.process_authoring_mode == "llm"
        cycle_obs["authoring_source"] = process_authoring_meta.authoring_source
        if process_authoring_meta.debug:
            overview = str(process_authoring_meta.debug.get("cycle_overview_narration") or "")
            cycle_obs["cycle_overview_moved_to_narration"] = bool(overview)
    if extraction_stats is not None:
        cycle_obs["raw_line_count"] = extraction_stats.raw_line_count
        cycle_obs["filtered_placeholder_count"] = extraction_stats.filtered_placeholder_count

    import logging as _lg
    _lg.getLogger(__name__).info(
        "[VTSE_AUTHOR] CYCLE_STAGE_COUNT=%d CYCLE_LLM_USED=%s CYCLE_STAGE_LABELS=%s "
        "CYCLE_OVERVIEW_MOVED_TO_NARRATION=%s CYCLE_EXPLANATION_COUNT=%d",
        n,
        cycle_obs["cycle_llm_consumed"],
        [s.label for s in steps],
        cycle_obs["cycle_overview_moved_to_narration"],
        cycle_obs["cycle_explanation_count"],
    )

    return TeachingPlan(
        plan_id=stable_plan_id("cyc", key),
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
            representation_type="cycle",
            topic=topic_label,
            nodes=nodes,
            edges=edges,
            layout_hints={
                "grouping": "cycle",
                "preferred_layout": "cycle_ring",
                "emphasis": "loop_closure",
            },
        ),
        beats=beats,
        provenance={
            "authoring_source": authoring_source,
            "cycle_authoring": cycle_obs,
            "plan_summary": {
                "mode": "cycle_ring",
                "stage_count": n,
                "stage_labels": [s.label for s in steps],
                "loop_closure": True,
                **cycle_obs,
            },
        },
    )
