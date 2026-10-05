"""Deterministic strategy registry (metadata only — Phase 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

RepresentationType = Literal["hierarchy", "flow", "comparison", "cycle"]

STRATEGY_IDS = (
    "hierarchy_concept_intro",
    "clustered_trait_list",
    "comparison_contrast",
    "cycle_process",
    "linear_process",
)


@dataclass(frozen=True)
class TeachingStrategyDefinition:
    strategy_id: str
    version: str
    description: str
    representation_types: tuple[RepresentationType, ...]
    layout_family: str
    default_pacing_curve: tuple[str, ...]
    orchestration_profile: str = "beat_orchestration_v1"


_REGISTRY: dict[str, TeachingStrategyDefinition] = {
    "hierarchy_concept_intro": TeachingStrategyDefinition(
        strategy_id="hierarchy_concept_intro",
        version="1.0.0",
        description="Root concept with child traits or sub-concepts in a tree.",
        representation_types=("hierarchy",),
        layout_family="hierarchy_root_children",
        default_pacing_curve=("deliver", "reinforce", "reinforce", "reflect"),
    ),
    "clustered_trait_list": TeachingStrategyDefinition(
        strategy_id="clustered_trait_list",
        version="1.0.0",
        description="Hierarchy root with child trait branches (tree layout).",
        representation_types=("hierarchy",),
        layout_family="hierarchy_root_children",
        default_pacing_curve=("deliver", "deliver", "reinforce", "reinforce"),
    ),
    "comparison_contrast": TeachingStrategyDefinition(
        strategy_id="comparison_contrast",
        version="1.0.0",
        description="Side-by-side comparison with contrast emphasis.",
        representation_types=("comparison",),
        layout_family="comparison_split",
        default_pacing_curve=("deliver", "deliver", "reinforce", "reflect"),
    ),
    "cycle_process": TeachingStrategyDefinition(
        strategy_id="cycle_process",
        version="1.0.0",
        description="Cyclic process with ring layout and return edge.",
        representation_types=("cycle",),
        layout_family="cycle_ring",
        default_pacing_curve=("deliver", "reinforce", "visualize", "reinforce"),
    ),
    "linear_process": TeachingStrategyDefinition(
        strategy_id="linear_process",
        version="1.0.0",
        description="Left-to-right or vertical step flow.",
        representation_types=("flow",),
        layout_family="flow_progression",
        default_pacing_curve=("deliver", "reinforce", "visualize", "close"),
    ),
}


def list_strategies() -> list[TeachingStrategyDefinition]:
    return [_REGISTRY[sid] for sid in STRATEGY_IDS if sid in _REGISTRY]


def get_strategy(strategy_id: str) -> TeachingStrategyDefinition:
    if strategy_id not in _REGISTRY:
        raise KeyError(f"unknown VTSE strategy_id: {strategy_id!r}")
    return _REGISTRY[strategy_id]


def resolve_strategy_id_for_representation(
    representation_type: str,
    *,
    layout_hints: Optional[dict[str, Any]] = None,
    node_count: int = 0,
) -> str:
    """
    Deterministic strategy selection (Phase 1 — no ML).

    Mirrors coarse rules used by TimelinePlannerV3 layout hints.
    """
    rep = str(representation_type or "flow").strip().lower()
    hints = layout_hints or {}
    grouping = str(hints.get("grouping") or "").strip().lower()
    preferred = str(hints.get("preferred_layout") or "").strip().lower()

    if rep == "comparison":
        return "comparison_contrast"
    if rep == "cycle":
        return "cycle_process"
    if rep == "hierarchy":
        if grouping in ("cluster", "clustered", "grouped") or node_count >= 4:
            return "clustered_trait_list"
        return "hierarchy_concept_intro"
    if rep == "flow":
        if grouping in ("cluster", "clustered", "grouped"):
            return "clustered_trait_list"
        if preferred in ("vertical_flow", "vertical", "column"):
            return "hierarchy_concept_intro"
        return "linear_process"
    return "linear_process"
