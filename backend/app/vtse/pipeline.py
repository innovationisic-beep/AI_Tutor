"""VTSE shell pipeline hooks (Zone 1 — always on)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.vtse.compiler.cir_bridge import teaching_plan_from_cir_dict
from app.vtse.compiler.vtse_compiler import VTSECompiler, VTSECompileResult
from app.vtse.models.plan import TeachingPlan

logger = logging.getLogger(__name__)


def build_vtse_observability(
    *,
    plan: TeachingPlan,
    compile_result: VTSECompileResult,
    authoring_source: str,
    compiler_path: str,
    strategy_selection: Any | None = None,
) -> dict[str, Any]:
    """Observability payload for timeline + debug strips."""
    summary = plan.provenance.get("plan_summary")
    sel_from_plan = plan.provenance.get("strategy_selection")
    payload: dict[str, Any] = {
        "vtse_enabled": True,
        "tdsl_version": compile_result.tdsl_version,
        "strategy_id": compile_result.strategy_id,
        "plan_id": compile_result.plan_id,
        "compiler_path": compiler_path,
        "compiler_version": VTSECompiler.compiler_version,
        "authoring_source": authoring_source,
        "plan_summary": summary if isinstance(summary, dict) else {},
        "pedagogical_roles": {b.beat_id: b.pedagogical_role for b in plan.beats},
        "beat_roles": [
            {"beat_id": b.beat_id, "role": b.pedagogical_role, "focus": b.focus_node_id}
            for b in sorted(plan.beats, key=lambda x: x.index)
        ],
        "visual_slots": {
            b.beat_id: dict(b.metadata.get("vtse_slot") or {})
            for b in plan.beats
            if isinstance(getattr(b, "metadata", None), dict)
            and isinstance(b.metadata.get("vtse_slot"), dict)
        },
    }
    if strategy_selection is not None:
        payload["selected_strategy"] = strategy_selection.strategy_id
        payload["strategy_reason"] = strategy_selection.strategy_reason
        payload["authoring_mode"] = strategy_selection.authoring_mode
        payload["semantic_shape"] = strategy_selection.semantic_shape
    elif isinstance(sel_from_plan, dict):
        payload["selected_strategy"] = sel_from_plan.get("selected_strategy")
        payload["strategy_reason"] = sel_from_plan.get("strategy_reason")
        payload["authoring_mode"] = sel_from_plan.get("authoring_mode")
        payload["semantic_shape"] = sel_from_plan.get("semantic_shape")
    if isinstance(summary, dict):
        payload["beat_generation_summary"] = summary.get("beat_generation_summary")
    process_authoring = plan.provenance.get("process_authoring")
    if isinstance(process_authoring, dict):
        payload["process_authoring"] = process_authoring
    return payload


def apply_vtse_shell_to_cir_dict(
    cir: dict[str, Any],
    *,
    session_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """
    CIR → TeachingPlan → CIR pass-through (always on).

    Returns (cir_for_compile, vtse_observability_dict).
    """
    plan = teaching_plan_from_cir_dict(
        cir,
        session_id=session_id,
        topic_id=topic_id,
        concept_id=concept_id,
    )

    compiled = VTSECompiler().compile_to_cir_dict(plan)

    observability = build_vtse_observability(
        plan=plan,
        compile_result=compiled,
        authoring_source="cir_lift_pass_through",
        compiler_path=compiled.compiler_path,
    )

    logger.info(
        "[VTSE] shell_pass_through strategy_id=%s plan_id=%s compiler_path=%s",
        compiled.strategy_id,
        compiled.plan_id,
        compiled.compiler_path,
    )

    return compiled.cir, observability


def stamp_timeline_vtse_metadata(
    timeline: dict[str, Any],
    vtse_obs: Optional[dict[str, Any]],
    *,
    vtse_visuals: Optional[dict[str, Any]] = None,
    concept_id: str = "",
) -> dict[str, Any]:
    """Attach VTSE observability block to timeline.metadata (non-breaking)."""
    if not vtse_obs:
        return timeline

    meta = timeline.setdefault("metadata", {})
    if not isinstance(meta, dict):
        return timeline

    meta["vtse"] = {
        "enabled": bool(vtse_obs.get("vtse_enabled")),
        "tdsl_version": vtse_obs.get("tdsl_version"),
        "strategy_id": vtse_obs.get("strategy_id"),
        "plan_id": vtse_obs.get("plan_id"),
        "compiler_path": vtse_obs.get("compiler_path"),
        "compiler_version": vtse_obs.get("compiler_version"),
        "authoring_source": vtse_obs.get("authoring_source"),
        "plan_summary": vtse_obs.get("plan_summary"),
    }

    roles = vtse_obs.get("pedagogical_roles") or {}
    if isinstance(roles, dict):
        for beat in timeline.get("beats") or []:
            if not isinstance(beat, dict):
                continue
            bid = str(beat.get("beat_id") or "")
            role = roles.get(bid)
            if role:
                bmeta = beat.setdefault("metadata", {})
                if isinstance(bmeta, dict):
                    bmeta["pedagogical_role"] = role

    if vtse_visuals:
        from app.services.vtse_visuals.stamp import safe_attach_vtse_visuals

        slots = vtse_obs.get("visual_slots") if isinstance(vtse_obs, dict) else {}
        safe_attach_vtse_visuals(
            timeline,
            slots_by_beat=slots if isinstance(slots, dict) else {},
            package=vtse_visuals,
            concept_id=concept_id,
        )

    return timeline
