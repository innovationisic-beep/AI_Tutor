"""Authoring context — normalized semantics + detected shape for strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.vtse.authoring.semantic_extract import (
    AuthoringSemanticDraft,
    TraitDraft,
    extract_authoring_semantics,
)
from app.vtse.authoring.process_step_schema import ProcessLLMDraftV1
from app.vtse.authoring.semantic_shape import (
    ComparisonSidesDraft,
    SemanticShape,
    ShapeDetectionMeta,
    compute_resolved_strategy_step_count,
    detect_semantic_shape,
)

AuthoringMode = Literal[
    "flat",
    "anchor_plus_traits",
    "comparison_paired",
    "cycle_ring",
    "linear_sequential",
]


@dataclass(frozen=True)
class AuthoringContext:
    """Inputs for deterministic plan building and strategy selection."""

    draft: AuthoringSemanticDraft
    semantic_shape: SemanticShape
    shape_cues: tuple[str, ...]
    comparison: ComparisonSidesDraft | None
    process_steps: tuple[TraitDraft, ...]
    has_template_steps: bool
    representation_type: str
    rag_context: str | None = None
    process_llm_draft: ProcessLLMDraftV1 | None = None
    process_llm_debug: dict[str, Any] | None = None
    shape_detection_meta: ShapeDetectionMeta | None = None
    resolved_strategy_step_count: int = 0

    @property
    def topic_label(self) -> str:
        return self.draft.topic_label

    @property
    def concept_label(self) -> str:
        return self.draft.concept_label

    @property
    def traits(self) -> tuple[TraitDraft, ...]:
        return self.draft.traits


def build_authoring_context(
    *,
    topic_name: str,
    concept: str,
    rag_context: str | None = None,
    trait_steps: list[dict[str, Any]] | None = None,
    source: str = "deterministic_extract",
    comparison_llm_json: dict | None = None,
    process_llm_draft: ProcessLLMDraftV1 | None = None,
    process_llm_debug: dict[str, Any] | None = None,
    force_shape: SemanticShape | None = None,
    opening_narration: str = "",
) -> AuthoringContext:
    draft = extract_authoring_semantics(
        topic_name=topic_name,
        concept=concept,
        rag_context=rag_context,
        trait_steps=trait_steps,
        source=source,
        opening_narration=opening_narration,
    )
    shape, cues, comparison, rep, shape_meta = detect_semantic_shape(
        topic_name=topic_name,
        concept=concept,
        rag_context=rag_context,
        trait_steps=trait_steps,
        draft=draft,
        comparison_llm_json=comparison_llm_json,
        force_shape=force_shape,
    )
    steps = draft.traits
    if shape == "comparison" and comparison is not None:
        steps = comparison.left_traits + comparison.right_traits
    resolved_count = compute_resolved_strategy_step_count(
        semantic_shape=shape,
        comparison=comparison,
        draft=draft,
        rag_context=rag_context,
        concept=concept,
        process_llm_draft=process_llm_draft,
    )
    return AuthoringContext(
        draft=draft,
        semantic_shape=shape,
        shape_cues=cues,
        comparison=comparison,
        process_steps=steps,
        has_template_steps=bool(trait_steps and len(trait_steps) >= 3),
        representation_type=rep,
        rag_context=rag_context,
        process_llm_draft=process_llm_draft,
        process_llm_debug=process_llm_debug,
        shape_detection_meta=shape_meta,
        resolved_strategy_step_count=resolved_count,
    )
