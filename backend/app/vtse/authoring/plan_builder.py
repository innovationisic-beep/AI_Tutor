"""Dispatch TeachingPlan construction from authoring context + strategy selection."""

from __future__ import annotations

from app.vtse.authoring.context import AuthoringContext
from app.vtse.authoring.semantic_shape import (
    process_steps_for_cycle_with_stats,
    process_steps_for_linear_with_stats,
    process_steps_for_shape,
)
from app.vtse.models.plan import TeachingPlan
from app.vtse.selectors.strategy_selector import (
    STRATEGY_CLUSTERED,
    STRATEGY_COMPARISON,
    STRATEGY_CYCLE,
    STRATEGY_LINEAR,
    StrategySelection,
    select_authoring_strategy,
)

_HIERARCHY_STRATEGIES = frozenset({STRATEGY_CLUSTERED, "hierarchy_concept_intro"})
from app.vtse.strategies.clustered_trait_list import (
    build_clustered_trait_list_plan,
    build_clustered_trait_list_plan_flat,
)
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
from app.vtse.strategies.cycle_process import build_cycle_process_plan
from app.vtse.strategies.linear_process import build_linear_process_plan


def build_teaching_plan(
    ctx: AuthoringContext,
    *,
    session_id: str,
    topic_id: str,
    concept: str,
    forced_strategy_id: str,
    flat_from_steps: bool = False,
) -> tuple[TeachingPlan, StrategySelection]:
    """Build a validated TeachingPlan from an authored forced strategy id."""
    selection = select_authoring_strategy(ctx, forced_strategy_id=forced_strategy_id)
    draft = ctx.draft

    if selection.strategy_id == STRATEGY_COMPARISON:
        if ctx.comparison is None:
            raise ValueError("comparison strategy requires comparison sides")
        plan = build_comparison_contrast_plan(
            topic_label=draft.topic_label,
            sides=ctx.comparison,
            session_id=session_id,
            topic_id=topic_id,
            concept_id=concept,
        )
    elif selection.strategy_id == STRATEGY_CYCLE:
        # Consume the cycle LLM draft (same pattern as linear process).
        # process_steps_for_cycle_with_stats routes through resolve_cycle_process_authoring
        # which caps stages at 7 and prioritises the LLM semantic output.
        cyc_steps, cyc_stats, cyc_meta, cyc_source = process_steps_for_cycle_with_stats(
            draft=draft,
            rag_context=ctx.rag_context,
            concept=concept,
            process_llm_draft=ctx.process_llm_draft,
            process_llm_debug=ctx.process_llm_debug,
        )
        plan = build_cycle_process_plan(
            topic_label=draft.topic_label,
            steps=cyc_steps,
            session_id=session_id,
            topic_id=topic_id,
            concept_id=concept,
            authoring_source=cyc_source,
            extraction_stats=cyc_stats,
            process_authoring_meta=cyc_meta,
        )
    elif selection.strategy_id == STRATEGY_LINEAR:
        steps, proc_stats, proc_meta, proc_source = process_steps_for_linear_with_stats(
            draft=draft,
            rag_context=ctx.rag_context,
            concept=concept,
            process_llm_draft=ctx.process_llm_draft,
            process_llm_debug=ctx.process_llm_debug,
        )
        plan = build_linear_process_plan(
            topic_label=draft.topic_label,
            steps=steps,
            session_id=session_id,
            topic_id=topic_id,
            concept_id=concept,
            extraction_stats=proc_stats,
            authoring_source=proc_source,
            process_authoring_meta=proc_meta,
        )
    elif selection.authoring_mode == "flat" and flat_from_steps and len(draft.traits) >= 3:
        plan = build_clustered_trait_list_plan_flat(
            topic_label=draft.topic_label,
            traits=draft.traits,
            session_id=session_id,
            topic_id=topic_id,
            concept_id=concept,
        )
    else:
        plan = build_clustered_trait_list_plan(
            draft,
            session_id=session_id,
            topic_id=topic_id,
            concept_id=concept,
        )

    summary = dict(plan.provenance.get("plan_summary") or {})
    summary.update(
        {
            "selected_strategy": selection.strategy_id,
            "strategy_reason": selection.strategy_reason,
            "authoring_mode": selection.authoring_mode,
            "semantic_shape": selection.semantic_shape,
            "shape_cues": list(ctx.shape_cues),
        },
    )
    plan.provenance["plan_summary"] = summary
    plan.provenance["strategy_selection"] = {
        "selected_strategy": selection.strategy_id,
        "strategy_reason": selection.strategy_reason,
        "semantic_shape": selection.semantic_shape,
        "authoring_mode": selection.authoring_mode,
        "representation_type": selection.representation_type,
        "shape_cues": list(ctx.shape_cues),
        "strategy_confidence_score": selection.strategy_confidence_score,
        "strategy_selector_inputs": selection.strategy_selector_inputs,
    }
    if ctx.shape_detection_meta is not None:
        meta = ctx.shape_detection_meta
        plan.provenance["shape_detection"] = {
            "concept_title_used_for_shape_detection": meta.concept_title_used,
            "semantic_detection_priority_order": list(meta.semantic_detection_priority_order),
            "winning_signal": meta.winning_signal,
            "strategy_confidence_score": meta.strategy_confidence_score,
            "detection_layers": {
                k: list(v) for k, v in meta.detection_layers.items()
            },
        }
    if (
        draft.hierarchy_hygiene is not None
        and selection.strategy_id in _HIERARCHY_STRATEGIES
    ):
        summary = dict(plan.provenance.get("plan_summary") or {})
        summary["hierarchy_extraction"] = draft.hierarchy_hygiene.to_debug_dict()
        plan.provenance["plan_summary"] = summary
        plan.provenance["hierarchy_extraction"] = draft.hierarchy_hygiene.to_debug_dict()

    # Hierarchy authoring observability: mode + concise label count
    if selection.strategy_id in _HIERARCHY_STRATEGIES:
        plan_summary = dict(plan.provenance.get("plan_summary") or {})
        source = str(draft.source or "")
        hierarchy_obs = plan.provenance.get("hierarchy_layout") or {}
        hierarchy_obs = dict(hierarchy_obs)
        hierarchy_obs["hierarchy_authoring_mode"] = (
            "llm" if "llm" in source else "deterministic"
        )
        hierarchy_obs["hierarchy_llm_enabled"] = "llm" in source
        hierarchy_obs["hierarchy_concise_label_count"] = len(draft.traits)
        hierarchy_obs["hierarchy_fallback_trigger_reason"] = (
            None if "llm" in source else "llm_disabled_or_skipped"
        )
        plan_summary["hierarchy_authoring_observability"] = hierarchy_obs
        plan.provenance["plan_summary"] = plan_summary

    attach_beat_generation_summary(plan)
    return plan, selection


def attach_beat_generation_summary(plan: TeachingPlan) -> None:
    """Add beat_generation_summary for observability."""
    summary = dict(plan.provenance.get("plan_summary") or {})
    summary["beat_generation_summary"] = [
        {
            "beat_id": b.beat_id,
            "role": b.pedagogical_role,
            "focus": b.focus_node_id,
            "pacing": b.pacing_mode,
        }
        for b in sorted(plan.beats, key=lambda x: x.index)
    ]
    plan.provenance["plan_summary"] = summary
