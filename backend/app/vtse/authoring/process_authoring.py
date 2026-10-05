"""Resolve linear process and cycle ring steps: authored draft primary, deterministic RAG fallback."""

from __future__ import annotations

from typing import Any

from app.vtse.authoring.process_step_schema import (
    ProcessAuthoringMeta,
    ProcessLLMDraftV1,
    trait_drafts_from_process_llm,
    validate_process_llm_draft,
)
from app.vtse.authoring.process_steps import (
    ProcessStepExtractionStats,
    coalesce_process_trait_steps,
    extract_process_steps_from_rag,
    filter_process_trait_steps,
)
from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft, TraitDraft
from app.vtse.authoring.semantic_shape import _default_linear_process_steps

_AUTHORING_SOURCE_LLM = "vtse_linear_process_llm_v1"
_AUTHORING_SOURCE_DETERMINISTIC = "vtse_linear_process_storyboard_v1"

_AUTHORING_SOURCE_CYCLE_LLM = "vtse_cycle_process_llm_v1"
_AUTHORING_SOURCE_CYCLE_DETERMINISTIC = "vtse_cycle_process_deterministic_v1"
_CYCLE_MAX_STEPS = 7


def resolve_linear_process_authoring(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
    process_llm_draft: ProcessLLMDraftV1 | None = None,
    process_llm_raw: dict[str, Any] | None = None,
    process_llm_debug: dict[str, Any] | None = None,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats, ProcessAuthoringMeta, str]:
    """
    Primary: validated LLM semantic draft.
    Secondary: deterministic RAG extraction.
    """
    llm_attempted = bool(process_llm_draft or process_llm_raw or process_llm_debug)
    validation_debug: dict[str, Any] = dict(process_llm_debug or {})

    if process_llm_draft is None and process_llm_raw:
        process_llm_draft, validation_debug = validate_process_llm_draft(
            process_llm_raw,
            rag_context=rag_context,
        )

    fallback_reason = str(validation_debug.get("fallback_trigger_reason") or "llm_unavailable")
    if process_llm_draft is not None:
        traits = trait_drafts_from_process_llm(process_llm_draft)
        if len(traits) >= 3:
            stats = ProcessStepExtractionStats(
                process_step_count=len(traits),
                process_scene_count=len(traits),
                raw_line_count=len(process_llm_draft.steps),
            )
            expansion = validation_debug.get("semantic_expansion_ratio")
            if expansion is None:
                from app.vtse.authoring.process_step_schema import compute_semantic_expansion_ratio

                expansion = compute_semantic_expansion_ratio(
                    process_llm_draft,
                    rag_context=rag_context,
                )
            meta = ProcessAuthoringMeta(
                process_authoring_mode="llm",
                llm_process_steps_generated=len(traits),
                semantic_process_confidence=process_llm_draft.semantic_process_confidence,
                renderer_contract_valid=True,
                narration_richness_level=process_llm_draft.narration_richness_level,
                authoring_source=_AUTHORING_SOURCE_LLM,
                narration_generation_source="llm_semantic",
                deterministic_override_detected=False,
                semantic_expansion_ratio=float(expansion) if expansion is not None else None,
                schema_clip_events=int(validation_debug.get("schema_clip_events") or 0),
                debug=validation_debug,
            )
            return traits, stats, meta, _AUTHORING_SOURCE_LLM
        fallback_reason = "validation_insufficient_steps"

    if process_llm_draft is None and process_llm_raw is not None:
        fallback_reason = str(
            validation_debug.get("validation_failure_reason") or "validation_failed",
        )

    steps, stats, _ = _deterministic_linear_steps(
        draft=draft,
        rag_context=rag_context,
        concept=concept,
    )
    meta = ProcessAuthoringMeta(
        process_authoring_mode="deterministic",
        llm_process_steps_generated=(
            len(process_llm_draft.steps) if process_llm_draft else None
        ),
        semantic_process_confidence=(
            process_llm_draft.semantic_process_confidence if process_llm_draft else None
        ),
        renderer_contract_valid=True,
        fallback_trigger_reason=fallback_reason if llm_attempted else None,
        narration_richness_level="deterministic_v1",
        authoring_source=_AUTHORING_SOURCE_DETERMINISTIC,
        narration_generation_source="deterministic_rag_parser",
        deterministic_override_detected=llm_attempted,
        debug=validation_debug if llm_attempted else None,
    )
    return steps, stats, meta, _AUTHORING_SOURCE_DETERMINISTIC


def _deterministic_linear_steps(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats, None]:
    rag_steps, rag_stats = extract_process_steps_from_rag(rag_context, concept)
    if len(rag_steps) >= 3:
        return rag_steps, rag_stats, None

    if len(rag_steps) >= 1:
        coalesced = coalesce_process_trait_steps(list(rag_steps), concept=concept)
        if len(coalesced) >= 3:
            merged = ProcessStepExtractionStats(
                filtered_placeholder_count=rag_stats.filtered_placeholder_count,
                filtered_practice_nodes=rag_stats.filtered_practice_nodes,
                process_step_count=len(coalesced),
                process_scene_count=len(coalesced),
                raw_line_count=rag_stats.raw_line_count,
            )
            return coalesced, merged, None

    steps = list(draft.traits)
    if steps:
        filtered, filt_stats = filter_process_trait_steps(steps, concept=concept)
        if len(filtered) >= 3:
            merged = ProcessStepExtractionStats(
                filtered_placeholder_count=rag_stats.filtered_placeholder_count + filt_stats.filtered_placeholder_count,
                filtered_practice_nodes=rag_stats.filtered_practice_nodes + filt_stats.filtered_practice_nodes,
                process_step_count=filt_stats.process_step_count,
                process_scene_count=filt_stats.process_scene_count,
                raw_line_count=rag_stats.raw_line_count + filt_stats.raw_line_count,
            )
            return filtered, merged, None

    defaults = _default_linear_process_steps(concept)
    merged = ProcessStepExtractionStats(
        filtered_placeholder_count=rag_stats.filtered_placeholder_count,
        filtered_practice_nodes=rag_stats.filtered_practice_nodes,
        process_step_count=len(defaults),
        process_scene_count=len(defaults),
        raw_line_count=rag_stats.raw_line_count,
    )
    return defaults, merged, None


def resolve_cycle_process_authoring(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
    process_llm_draft: ProcessLLMDraftV1 | None = None,
    process_llm_raw: dict[str, Any] | None = None,
    process_llm_debug: dict[str, Any] | None = None,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats, ProcessAuthoringMeta, str]:
    """
    Cycle ring authoring: LLM primary → deterministic RAG fallback.

    Mirrors ``resolve_linear_process_authoring`` but:
    - Caps stages at ``_CYCLE_MAX_STEPS`` (7)
    - Uses cycle-specific authoring sources
    - Extracts cycle_overview_narration from debug for first-beat narration enrichment
    """
    import logging as _lg
    _log = _lg.getLogger(__name__)

    llm_attempted = bool(process_llm_draft or process_llm_raw or process_llm_debug)
    validation_debug: dict[str, Any] = dict(process_llm_debug or {})

    if process_llm_draft is None and process_llm_raw:
        process_llm_draft, validation_debug = validate_process_llm_draft(
            process_llm_raw,
            rag_context=rag_context,
        )

    cycle_overview = str(validation_debug.get("cycle_overview_narration") or "").strip()

    fallback_reason = str(validation_debug.get("fallback_trigger_reason") or "llm_unavailable")
    if process_llm_draft is not None:
        # Clamp to cycle max
        clamped_steps = process_llm_draft.steps[:_CYCLE_MAX_STEPS]
        if len(clamped_steps) >= 3:
            traits = _cycle_traits_from_process_llm(clamped_steps, cycle_overview=cycle_overview)
            stats = ProcessStepExtractionStats(
                process_step_count=len(traits),
                process_scene_count=len(traits),
                raw_line_count=len(process_llm_draft.steps),
            )
            expansion = validation_debug.get("semantic_expansion_ratio")
            if expansion is None:
                from app.vtse.authoring.process_step_schema import compute_semantic_expansion_ratio
                expansion = compute_semantic_expansion_ratio(
                    process_llm_draft, rag_context=rag_context
                )
            meta = ProcessAuthoringMeta(
                process_authoring_mode="llm",
                llm_process_steps_generated=len(traits),
                semantic_process_confidence=process_llm_draft.semantic_process_confidence,
                renderer_contract_valid=True,
                narration_richness_level=process_llm_draft.narration_richness_level,
                authoring_source=_AUTHORING_SOURCE_CYCLE_LLM,
                narration_generation_source="llm_semantic",
                deterministic_override_detected=False,
                semantic_expansion_ratio=float(expansion) if expansion is not None else None,
                schema_clip_events=int(validation_debug.get("schema_clip_events") or 0),
                debug=validation_debug,
            )
            _log.info(
                "[VTSE_AUTHOR] CYCLE_LLM_USED stages=%d labels=%s overview_present=%s",
                len(traits),
                [t.label for t in traits],
                bool(cycle_overview),
            )
            return traits, stats, meta, _AUTHORING_SOURCE_CYCLE_LLM
        fallback_reason = "validation_insufficient_steps"

    if process_llm_draft is None and process_llm_raw is not None:
        fallback_reason = str(
            validation_debug.get("validation_failure_reason") or "validation_failed"
        )

    # Deterministic fallback
    steps, stats = _deterministic_cycle_steps(
        draft=draft,
        rag_context=rag_context,
        concept=concept,
    )
    meta = ProcessAuthoringMeta(
        process_authoring_mode="deterministic",
        llm_process_steps_generated=(
            len(process_llm_draft.steps) if process_llm_draft else None
        ),
        semantic_process_confidence=(
            process_llm_draft.semantic_process_confidence if process_llm_draft else None
        ),
        renderer_contract_valid=True,
        fallback_trigger_reason=fallback_reason if llm_attempted else None,
        narration_richness_level="deterministic_v1",
        authoring_source=_AUTHORING_SOURCE_CYCLE_DETERMINISTIC,
        narration_generation_source="deterministic_rag_parser",
        deterministic_override_detected=llm_attempted,
        debug=validation_debug if llm_attempted else None,
    )
    _log.info(
        "[VTSE_AUTHOR] CYCLE_DETERMINISTIC_FALLBACK stages=%d reason=%s",
        len(steps),
        fallback_reason if llm_attempted else "llm_not_attempted",
    )
    return steps, stats, meta, _AUTHORING_SOURCE_CYCLE_DETERMINISTIC


def _cycle_traits_from_process_llm(
    steps: tuple,
    *,
    cycle_overview: str = "",
) -> tuple[TraitDraft, ...]:
    """
    Map validated cycle LLM steps → ``TraitDraft`` for ``build_cycle_process_plan``.

    If cycle_overview is provided, it is prepended to the first stage's narration
    so the spoken opening introduces the whole cycle before diving into stage 1.
    """
    out: list[TraitDraft] = []
    for i, step in enumerate(steps):
        narr = step.narration_text
        # Prepend overview to the anchor (first) stage narration
        if i == 0 and cycle_overview and cycle_overview.lower() not in narr.lower():
            from app.vtse.authoring.semantic_extract import _clip
            narr = _clip(f"{cycle_overview} {narr}", 500)
        out.append(
            TraitDraft(
                label=step.concise_node_label,
                summary=step.explanation_text,
                narration=narr,
                kind="process",
            )
        )
    return tuple(out)


def _deterministic_cycle_steps(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats]:
    """
    Extract cycle stages from RAG without LLM.

    Uses the same RAG extraction as linear, then clamps to cycle range (3–7).
    Falls back to generic ``_default_cycle_steps`` when extraction is thin.
    """
    from app.vtse.authoring.semantic_shape import _default_cycle_steps

    rag_steps, rag_stats = extract_process_steps_from_rag(rag_context, concept)
    # Clamp to cycle range
    rag_steps = rag_steps[:_CYCLE_MAX_STEPS]

    if len(rag_steps) >= 3:
        return rag_steps, rag_stats

    # Coalesce short extraction
    if len(rag_steps) >= 1:
        coalesced = coalesce_process_trait_steps(list(rag_steps), concept=concept)
        coalesced = coalesced[:_CYCLE_MAX_STEPS]
        if len(coalesced) >= 3:
            merged = ProcessStepExtractionStats(
                filtered_placeholder_count=rag_stats.filtered_placeholder_count,
                filtered_practice_nodes=rag_stats.filtered_practice_nodes,
                process_step_count=len(coalesced),
                process_scene_count=len(coalesced),
                raw_line_count=rag_stats.raw_line_count,
            )
            return tuple(coalesced), merged

    # Draft traits fallback
    steps = list(draft.traits)
    if steps:
        filtered, filt_stats = filter_process_trait_steps(steps, concept=concept)
        filtered = filtered[:_CYCLE_MAX_STEPS]
        if len(filtered) >= 3:
            merged = ProcessStepExtractionStats(
                filtered_placeholder_count=rag_stats.filtered_placeholder_count + filt_stats.filtered_placeholder_count,
                filtered_practice_nodes=rag_stats.filtered_practice_nodes + filt_stats.filtered_practice_nodes,
                process_step_count=len(filtered),
                process_scene_count=len(filtered),
                raw_line_count=rag_stats.raw_line_count + filt_stats.raw_line_count,
            )
            return tuple(filtered), merged

    # Generic defaults
    defaults = _default_cycle_steps(concept)
    merged = ProcessStepExtractionStats(
        filtered_placeholder_count=rag_stats.filtered_placeholder_count,
        filtered_practice_nodes=rag_stats.filtered_practice_nodes,
        process_step_count=len(defaults),
        process_scene_count=len(defaults),
        raw_line_count=rag_stats.raw_line_count,
    )
    return defaults, merged
