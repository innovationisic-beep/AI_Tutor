"""Forced VTSE strategy dispatch from authored ``vtse_template``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.vtse.authoring.context import AuthoringContext, AuthoringMode

STRATEGY_CLUSTERED = "clustered_trait_list"
STRATEGY_COMPARISON = "comparison_contrast"
STRATEGY_CYCLE = "cycle_process"
STRATEGY_LINEAR = "linear_process"


@dataclass(frozen=True)
class StrategySelection:
    strategy_id: str
    strategy_reason: str
    semantic_shape: str
    authoring_mode: AuthoringMode
    representation_type: str
    strategy_confidence_score: float | None = None
    strategy_selector_inputs: dict[str, Any] | None = None


def _selector_inputs(ctx: AuthoringContext) -> dict[str, Any]:
    meta = ctx.shape_detection_meta
    return {
        "semantic_shape": ctx.semantic_shape,
        "resolved_strategy_step_count": ctx.resolved_strategy_step_count,
        "raw_trait_count": len(ctx.traits),
        "process_step_preview_count": len(ctx.process_steps),
        "has_template_steps": ctx.has_template_steps,
        "concept_title_used_for_shape_detection": (
            meta.concept_title_used if meta else ctx.concept_label
        ),
        "winning_shape_signal": meta.winning_signal if meta else None,
    }


def select_authoring_strategy(
    ctx: AuthoringContext,
    *,
    forced_strategy_id: str,
) -> StrategySelection:
    """
    Lock strategy from an authored VTSE template (``forced_strategy_id``).

    Automatic shape-based strategy selection was removed; Zone 1 requires a
    curriculum ``vtse_template`` and always passes the template strategy id.
    """
    sid = str(forced_strategy_id or "").strip()
    if not sid:
        raise ValueError("forced_strategy_id is required (authored vtse_template)")
    return _forced_strategy_selection(ctx, sid)


def _forced_strategy_selection(ctx: AuthoringContext, strategy_id: str) -> StrategySelection:
    sid = str(strategy_id).strip()
    inputs = {**_selector_inputs(ctx), "forced_strategy_id": sid}
    confidence = 1.0
    if sid == STRATEGY_COMPARISON:
        return StrategySelection(
            strategy_id=STRATEGY_COMPARISON,
            strategy_reason="forced:vtse_template",
            semantic_shape="comparison",
            authoring_mode="comparison_paired",
            representation_type="comparison",
            strategy_confidence_score=confidence,
            strategy_selector_inputs=inputs,
        )
    if sid == STRATEGY_CYCLE:
        return StrategySelection(
            strategy_id=STRATEGY_CYCLE,
            strategy_reason="forced:vtse_template",
            semantic_shape="cycle",
            authoring_mode="cycle_ring",
            representation_type="cycle",
            strategy_confidence_score=confidence,
            strategy_selector_inputs=inputs,
        )
    if sid == STRATEGY_LINEAR:
        return StrategySelection(
            strategy_id=STRATEGY_LINEAR,
            strategy_reason="forced:vtse_template",
            semantic_shape="linear_process",
            authoring_mode="linear_sequential",
            representation_type="flow",
            strategy_confidence_score=confidence,
            strategy_selector_inputs=inputs,
        )
    if sid == "hierarchy_concept_intro":
        return StrategySelection(
            strategy_id="hierarchy_concept_intro",
            strategy_reason="forced:vtse_template",
            semantic_shape="trait_list",
            authoring_mode="anchor_plus_traits",
            representation_type="hierarchy",
            strategy_confidence_score=confidence,
            strategy_selector_inputs=inputs,
        )
    # clustered_trait_list and unknown → clustered flat when traits present
    mode: AuthoringMode = "flat" if ctx.has_template_steps and len(ctx.traits) >= 3 else "anchor_plus_traits"
    return StrategySelection(
        strategy_id=STRATEGY_CLUSTERED,
        strategy_reason="forced:vtse_template",
        semantic_shape="trait_list",
        authoring_mode=mode,
        representation_type="hierarchy",
        strategy_confidence_score=confidence,
        strategy_selector_inputs=inputs,
    )
