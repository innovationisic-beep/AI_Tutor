"""Zone 1 VTSE authoring entry (TeachingPlan → CIR → timeline).

Template-only: requires CurriculumConcept.vtse_template. No auto strategy select.
"""

from __future__ import annotations

import logging
from typing import Any

from app.cir.validate import validate_cir_v1
from app.services.timeline_planner_v3 import TimelinePlannerResult, TimelinePlannerV3
from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.pipeline import build_vtse_observability, stamp_timeline_vtse_metadata

logger = logging.getLogger(__name__)

VTSE_AUTHORING_PLANNER_SOURCE = "timeline_v3_from_vtse_authoring_v1"


async def try_zone1_vtse_authoring(
    *,
    planner: TimelinePlannerV3,
    session_id: str,
    topic_id_str: str | None,
    topic_name: str,
    concept: str,
    rag_service: Any | None = None,
    cir_rag_context: str | None = None,
    teaching_objective: str | None = None,
    cluster_context: str | None = None,
    student_profile_dict: dict[str, Any] | None = None,
    trait_steps: list[dict[str, Any]] | None = None,
    vtse_template: dict[str, Any] | None = None,
    vtse_visuals: dict[str, Any] | None = None,
    vtse_visual_concept_id: str = "",
    compile_validated_cir: Any,
    continuity: dict[str, Any] | None = None,
) -> TimelinePlannerResult | None:
    """
    Zone 1 timeline via authored VTSE template only.

    Returns None when template missing/invalid, or authoring fails.
    Never auto-selects a strategy from notes/title cues.
    """
    _ = teaching_objective, cluster_context  # retained for call-site compatibility

    from app.services.curriculum.concept_vtse_context import (
        format_vtse_template_as_rag_context,
    )
    from app.services.curriculum.concept_vtse_template import (
        force_shape_for_strategy,
        materialize_vtse_template_inputs,
        normalize_vtse_template,
    )
    from app.vtse.authoring.authored_expand import (
        expand_authored_vtse_template,
        prepend_spoken_opening,
    )

    authored = None
    try:
        authored = normalize_vtse_template(vtse_template) if vtse_template else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[VTSE_AUTHOR] authored_template_invalid detail=%s", exc)
        authored = None

    if authored is None:
        logger.info(
            "[VTSE_AUTHOR] skip_no_template concept=%s — auto strategy disabled",
            (concept or "")[:80],
        )
        return None

    try:
        outline_context = format_vtse_template_as_rag_context(
            authored,
            concept_label=concept,
        )
        # Prefer template outline over TopicNote RAG for plan grounding.
        rag_for_ctx = outline_context or (cir_rag_context or "")

        comp_json, proc_draft, authored_steps, forced_id = materialize_vtse_template_inputs(
            authored,
            topic_name=topic_name,
            concept=concept,
        )
        expand_debug: dict[str, Any] = {
            "authored_vtse_template": True,
            "strategy_id": forced_id,
            "template_only": True,
        }
        used_llm_expand = False
        if rag_service is not None:
            exp_comp, exp_proc, exp_steps, exp_dbg = await expand_authored_vtse_template(
                rag_service=rag_service,
                template=authored,
                topic_name=topic_name,
                concept=concept,
                student_profile=student_profile_dict,
                continuity=continuity,
            )
            expand_debug["expand"] = exp_dbg
            if exp_dbg.get("expand_ok"):
                used_llm_expand = True
                if exp_comp is not None:
                    comp_json = exp_comp
                if exp_proc is not None:
                    proc_draft = exp_proc
                if exp_steps is not None:
                    authored_steps = exp_steps
            else:
                logger.warning(
                    "[VTSE_AUTHOR] authored_expand_fallback reason=%s — using outline text",
                    exp_dbg.get("expand_error"),
                )
        else:
            expand_debug["expand_skipped"] = "no_rag_service"

        force_shape = force_shape_for_strategy(forced_id)  # type: ignore[arg-type]
        steps_for_ctx = authored_steps if authored_steps is not None else trait_steps
        cluster_opening = str((expand_debug.get("expand") or {}).get("opening_narration") or "").strip()
        if (
            used_llm_expand
            and forced_id == "clustered_trait_list"
            and cluster_opening
            and steps_for_ctx
        ):
            first = dict(steps_for_ctx[0])
            first["narration"] = prepend_spoken_opening(
                str(first.get("narration") or ""),
                cluster_opening,
            )
            steps_for_ctx = [first, *list(steps_for_ctx[1:])]
        ctx = build_authoring_context(
            topic_name=topic_name,
            concept=concept,
            rag_context=rag_for_ctx,
            trait_steps=steps_for_ctx,
            source=(
                "authored_vtse_template_expanded"
                if used_llm_expand
                else "authored_vtse_template"
            ),
            comparison_llm_json=comp_json,
            process_llm_draft=proc_draft,
            process_llm_debug=expand_debug,
            force_shape=force_shape,  # type: ignore[arg-type]
            opening_narration=(
                str((expand_debug.get("expand") or {}).get("opening_narration") or "")
                if used_llm_expand and forced_id == "hierarchy_concept_intro"
                else ""
            ),
        )
        flat = bool(steps_for_ctx and len(steps_for_ctx) >= 3)
        plan, selection = build_teaching_plan(
            ctx,
            session_id=session_id,
            topic_id=topic_id_str or "",
            concept=concept,
            flat_from_steps=flat,
            forced_strategy_id=forced_id,
        )
        compiled_cir = VTSECompiler().compile_to_cir_dict(plan)
        v = validate_cir_v1(compiled_cir.cir)
        if not v.ok or v.cir is None:
            logger.warning(
                "[VTSE_AUTHOR] authored_cir_validate_failed errors=%s",
                " | ".join(v.errors[:5]) if v.errors else "?",
            )
            return None

        authoring_source = (
            "authored_vtse_template_expanded"
            if used_llm_expand
            else "authored_vtse_template"
        )
        obs = build_vtse_observability(
            plan=plan,
            compile_result=compiled_cir,
            authoring_source=authoring_source,
            compiler_path="teaching_plan_authoring_to_cir_v1",
            strategy_selection=selection,
        )

        dumped = v.cir.model_dump(mode="json", by_alias=True)

        result = compile_validated_cir(
            planner=planner,
            dumped=dumped,
            session_id=session_id,
            topic_id_str=topic_id_str,
            concept=concept,
            from_llm=used_llm_expand,
        )
        tl = result.timeline
        if isinstance(tl, dict):
            stamp_timeline_vtse_metadata(
                tl,
                obs,
                vtse_visuals=vtse_visuals,
                concept_id=vtse_visual_concept_id,
            )
        dbg = dict(result.cir_instruction_debug or {})
        dbg["vtse"] = obs
        dbg["authored_vtse_template"] = True
        dbg["authored_expanded_via_llm"] = used_llm_expand
        dbg["authored_expand_debug"] = expand_debug
        dbg["template_only"] = True
        dbg["using_vtse_authoring"] = True
        dbg["legacy_authoring_removed"] = True
        dbg["legacy_cir_llm_used"] = False
        dbg["emergency_fallback_used"] = False
        logger.info(
            "[VTSE_AUTHOR] authored_template strategy=%s expanded=%s concept=%s",
            forced_id,
            used_llm_expand,
            (concept or "")[:80],
        )
        return TimelinePlannerResult(
            timeline=tl if isinstance(tl, dict) else result.timeline,
            planner_source=VTSE_AUTHORING_PLANNER_SOURCE,
            cir_instruction_debug=dbg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[VTSE_AUTHOR] authored_template_failed detail=%s — no auto fallback",
            exc,
        )
        return None
