"""Deterministic semantic shape detection (no ML, no topic-specific hacks)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.vtse.authoring.comparison_rows import (
    ComparisonRow,
    ComparisonRowBuildStats,
    build_comparison_rows,
    rows_to_trait_drafts,
)
from app.cir.limits import CIR_V1_MAX_NODES
from app.vtse.authoring.process_steps import (
    ProcessStepExtractionStats,
    extract_process_steps_from_rag,
    filter_process_trait_steps,
)
from app.vtse.authoring.semantic_extract import (
    AuthoringSemanticDraft,
    TraitDraft,
    _clip,
    _lines_from_rag,
)

SemanticShape = Literal["trait_list", "comparison", "cycle", "linear_process"]

_VS_SPLIT = re.compile(r"\s+(?:vs\.?|versus)\s+", re.IGNORECASE)


_COMPARISON_CUES = (
    "compare",
    "contrast",
    "difference",
    "similarities",
    "differences",
    "side by side",
)
_CYCLE_CUES = (
    "cycle",
    "life cycle",
    "water cycle",
    "carbon cycle",
    "loop",
    "circulation",
    "recycle",
)
_LINEAR_CUES = (
    "process",
    "digestion",
    "photosynthesis",
    "flow",
    "sequence",
    "step by step",
    "stages",
    "pathway",
    "order of",
)


@dataclass(frozen=True)
class ComparisonSidesDraft:
    left_label: str
    right_label: str
    rows: tuple[ComparisonRow, ...] = ()
    row_stats: ComparisonRowBuildStats | None = None
    left_traits: tuple[TraitDraft, ...] = ()
    right_traits: tuple[TraitDraft, ...] = ()
    opening_narration: str = ""


@dataclass(frozen=True)
class ShapeDetectionMeta:
    """Observability for concept-first semantic shape detection."""

    concept_title_used: str
    semantic_detection_priority_order: tuple[str, ...]
    winning_signal: str
    strategy_confidence_score: float
    detection_layers: dict[str, tuple[str, ...]]


def _text_blob(*parts: str | None) -> str:
    return " ".join(p.strip().lower() for p in parts if p and str(p).strip())


def _cue_hits(blob: str, cues: tuple[str, ...]) -> list[str]:
    return [c for c in cues if c in blob]


def _split_comparison_topic(topic_name: str) -> tuple[str, str] | None:
    parts = _VS_SPLIT.split(topic_name.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = parts[0].strip(), parts[1].strip()
    if len(left) < 2 or len(right) < 2:
        return None
    return _clip(left, 80), _clip(right, 80)


def resolve_comparison_split(
    *,
    concept: str,
    topic_name: str,
) -> tuple[tuple[str, str] | None, str]:
    """Prefer key-concept title for ``A vs B`` detection over chapter name."""
    concept_split = _split_comparison_topic(concept)
    if concept_split:
        return concept_split, "concept_vs_split"
    topic_split = _split_comparison_topic(topic_name)
    if topic_split:
        return topic_split, "topic_vs_split"
    return None, ""


def _layer_cue_hits(
    *,
    concept: str,
    rag_context: str | None,
    topic_name: str,
    cues: tuple[str, ...],
) -> tuple[list[str], dict[str, tuple[str, ...]], str, float]:
    """
    Scan concept → rag → chapter in order; return first non-empty hit layer.
    """
    layers: list[tuple[str, str]] = [
        ("concept", _text_blob(concept)),
        ("rag", _text_blob(rag_context)),
        ("chapter", _text_blob(topic_name)),
    ]
    layer_hits: dict[str, tuple[str, ...]] = {}
    for layer_name, blob in layers:
        hits = tuple(_cue_hits(blob, cues))
        layer_hits[layer_name] = hits
        if hits:
            confidence = {"concept": 0.82, "rag": 0.74, "chapter": 0.66}[layer_name]
            return list(hits), layer_hits, f"{layer_name}:{hits[0]}", confidence
    return [], layer_hits, "", 0.0


def _default_comparison_traits(
    left_label: str,
    right_label: str,
    concept: str,
) -> tuple[tuple[TraitDraft, ...], tuple[TraitDraft, ...]]:
    base = concept or "these ideas"
    left = (
        TraitDraft(
            label="Grows",
            summary=f"{left_label} can grow and develop.",
            narration=f"{left_label} shows growth as part of {base}.",
        ),
        TraitDraft(
            label="Needs energy",
            summary=f"{left_label} uses energy from the environment.",
            narration=f"{left_label} needs energy to stay active.",
        ),
        TraitDraft(
            label="Reproduces",
            summary=f"{left_label} can produce offspring.",
            narration=f"{left_label} can reproduce over time.",
        ),
    )
    right = (
        TraitDraft(
            label="No growth",
            summary=f"{right_label} does not grow on its own.",
            narration=f"{right_label} does not grow the way {left_label.lower()} does.",
        ),
        TraitDraft(
            label="No metabolism",
            summary=f"{right_label} has no living metabolism.",
            narration=f"{right_label} does not use energy for life processes.",
        ),
        TraitDraft(
            label="No reproduction",
            summary=f"{right_label} does not reproduce biologically.",
            narration=f"{right_label} does not create offspring.",
        ),
    )
    return left, right


def _default_cycle_steps(concept: str) -> tuple[TraitDraft, ...]:
    topic = concept or "the cycle"
    return (
        TraitDraft(
            label="Stage 1",
            summary=f"First stage of {topic}.",
            narration=f"The cycle begins at the first stage of {topic}.",
            kind="process",
        ),
        TraitDraft(
            label="Stage 2",
            summary=f"Middle transformation in {topic}.",
            narration=f"Next, {topic} moves through a middle stage.",
            kind="process",
        ),
        TraitDraft(
            label="Stage 3",
            summary=f"Later stage of {topic}.",
            narration=f"Then the process continues to a later stage.",
            kind="process",
        ),
        TraitDraft(
            label="Return",
            summary=f"The cycle completes and returns.",
            narration=f"Finally, {topic} completes and the cycle can repeat.",
            kind="process",
        ),
    )


def _default_linear_process_steps(concept: str) -> tuple[TraitDraft, ...]:
    topic = concept or "the process"
    return (
        TraitDraft(
            label="Begin",
            summary=f"The process of {topic} begins with an initial stage.",
            narration=f"First, the process of {topic} begins.",
            kind="process",
        ),
        TraitDraft(
            label="Transform",
            summary=f"The middle stage changes materials during {topic}.",
            narration=f"Next, {topic} moves through a transformation stage.",
            kind="process",
        ),
        TraitDraft(
            label="Complete",
            summary=f"The process of {topic} reaches its outcome.",
            narration=f"Finally, the process of {topic} completes.",
            kind="process",
        ),
    )


def _build_comparison_sides(
    *,
    topic_name: str,
    concept: str,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    comparison_llm_json: dict | None = None,
) -> ComparisonSidesDraft:
    split = _split_comparison_topic(concept) or _split_comparison_topic(topic_name)
    if split:
        left_label, right_label = split
    else:
        left_label = draft.anchor_label or "Concept A"
        right_label = _clip(f"Other {concept}", 80)

    llm_rows: tuple[ComparisonRow, ...] = ()
    if comparison_llm_json:
        from app.vtse.authoring.comparison_rows import comparison_rows_from_llm_json

        llm_left = str(comparison_llm_json.get("left_label") or left_label).strip() or left_label
        llm_right = str(comparison_llm_json.get("right_label") or right_label).strip() or right_label
        llm_rows = comparison_rows_from_llm_json(
            comparison_llm_json,
            left_label=llm_left,
            right_label=llm_right,
        )
        left_label = llm_left
        right_label = llm_right

    rows, stats = build_comparison_rows(
        left_label=left_label,
        right_label=right_label,
        concept=concept,
        draft=draft,
        rag_context=rag_context,
        llm_rows=llm_rows or None,
    )
    left_traits, right_traits = rows_to_trait_drafts(rows)

    opening = ""
    if comparison_llm_json:
        opening = str(comparison_llm_json.get("opening_narration") or "").strip()[:400]
    return ComparisonSidesDraft(
        left_label=left_label,
        right_label=right_label,
        rows=rows,
        row_stats=stats,
        left_traits=left_traits,
        right_traits=right_traits,
        opening_narration=opening,
    )


def detect_semantic_shape(
    *,
    topic_name: str,
    concept: str,
    rag_context: str | None,
    trait_steps: list[dict[str, Any]] | None,
    draft: AuthoringSemanticDraft,
    comparison_llm_json: dict | None = None,
    force_shape: SemanticShape | None = None,
) -> tuple[SemanticShape, tuple[str, ...], ComparisonSidesDraft | None, str, ShapeDetectionMeta]:
    """
    Return (shape, cues, optional comparison sides, representation_type, detection meta).

    Priority: key concept title → concept RAG → chapter name → fallbacks.
    When ``force_shape`` is set (authored VTSE template), skip cue detection.
    """
    concept_title = _clip((concept or "").strip() or (topic_name or "").strip(), 120)
    priority_order = ("concept_title", "rag_context", "chapter_topic_name", "fallback_heuristics")
    cues: list[str] = []
    layer_maps: dict[str, tuple[str, ...]] = {}
    winning_signal = "default_trait_list"
    confidence = 0.42

    if force_shape == "comparison":
        comparison = _build_comparison_sides(
            topic_name=topic_name,
            concept=concept,
            draft=draft,
            rag_context=rag_context,
            comparison_llm_json=comparison_llm_json,
        )
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="forced:vtse_template",
            strategy_confidence_score=1.0,
            detection_layers={"forced": ("comparison",)},
        )
        return "comparison", ("forced:vtse_template",), comparison, "comparison", meta

    if force_shape == "cycle":
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="forced:vtse_template",
            strategy_confidence_score=1.0,
            detection_layers={"forced": ("cycle",)},
        )
        return "cycle", ("forced:vtse_template",), None, "cycle", meta

    if force_shape == "linear_process":
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="forced:vtse_template",
            strategy_confidence_score=1.0,
            detection_layers={"forced": ("linear_process",)},
        )
        return "linear_process", ("forced:vtse_template",), None, "flow", meta

    if force_shape == "trait_list":
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="forced:vtse_template",
            strategy_confidence_score=1.0,
            detection_layers={"forced": ("trait_list",)},
        )
        return "trait_list", ("forced:vtse_template",), None, "hierarchy", meta

    comp_split, split_signal = resolve_comparison_split(concept=concept, topic_name=topic_name)
    if comp_split:
        cues.append(split_signal)
        winning_signal = split_signal
        confidence = 0.94 if split_signal == "concept_vs_split" else 0.86
        comparison = _build_comparison_sides(
            topic_name=topic_name,
            concept=concept,
            draft=draft,
            rag_context=rag_context,
            comparison_llm_json=comparison_llm_json,
        )
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal=winning_signal,
            strategy_confidence_score=confidence,
            detection_layers={"comparison_split": (split_signal,)},
        )
        return "comparison", tuple(cues), comparison, "comparison", meta

    comp_hits, comp_layers, comp_signal, comp_conf = _layer_cue_hits(
        concept=concept,
        rag_context=rag_context,
        topic_name=topic_name,
        cues=_COMPARISON_CUES,
    )
    layer_maps.update({f"comparison_{k}": v for k, v in comp_layers.items()})
    if comp_hits:
        cues.extend(f"comparison:{h}" for h in comp_hits)
        winning_signal = comp_signal
        confidence = comp_conf
        comparison = _build_comparison_sides(
            topic_name=topic_name,
            concept=concept,
            draft=draft,
            rag_context=rag_context,
            comparison_llm_json=comparison_llm_json,
        )
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal=winning_signal,
            strategy_confidence_score=confidence,
            detection_layers=layer_maps,
        )
        return "comparison", tuple(cues), comparison, "comparison", meta

    if trait_steps and len(trait_steps) >= 3:
        cues.append("template_steps")
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="template_steps",
            strategy_confidence_score=0.78,
            detection_layers=layer_maps,
        )
        return "trait_list", tuple(cues), None, "hierarchy", meta

    cycle_hits, cycle_layers, cycle_signal, cycle_conf = _layer_cue_hits(
        concept=concept,
        rag_context=rag_context,
        topic_name=topic_name,
        cues=_CYCLE_CUES,
    )
    layer_maps.update({f"cycle_{k}": v for k, v in cycle_layers.items()})
    if cycle_hits:
        cues.extend(f"cycle:{h}" for h in cycle_hits)
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal=cycle_signal or f"cycle:{cycle_hits[0]}",
            strategy_confidence_score=cycle_conf or 0.75,
            detection_layers=layer_maps,
        )
        return "cycle", tuple(cues), None, "cycle", meta

    linear_hits, linear_layers, linear_signal, linear_conf = _layer_cue_hits(
        concept=concept,
        rag_context=rag_context,
        topic_name=topic_name,
        cues=_LINEAR_CUES,
    )
    layer_maps.update({f"linear_{k}": v for k, v in linear_layers.items()})
    if linear_hits:
        cues.extend(f"linear:{h}" for h in linear_hits)
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal=linear_signal or f"linear:{linear_hits[0]}",
            strategy_confidence_score=linear_conf or 0.73,
            detection_layers=layer_maps,
        )
        return "linear_process", tuple(cues), None, "flow", meta

    lines = _lines_from_rag(rag_context)
    if len(lines) >= 3:
        cues.append("rag_bullet_list")
        meta = ShapeDetectionMeta(
            concept_title_used=concept_title,
            semantic_detection_priority_order=priority_order,
            winning_signal="rag_bullet_list",
            strategy_confidence_score=0.58,
            detection_layers=layer_maps,
        )
        return "trait_list", tuple(cues), None, "hierarchy", meta

    cues.append("default_trait_list")
    meta = ShapeDetectionMeta(
        concept_title_used=concept_title,
        semantic_detection_priority_order=priority_order,
        winning_signal=winning_signal,
        strategy_confidence_score=confidence,
        detection_layers=layer_maps,
    )
    return "trait_list", tuple(cues), None, "hierarchy", meta


def compute_resolved_strategy_step_count(
    *,
    semantic_shape: SemanticShape,
    comparison: ComparisonSidesDraft | None,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
    process_llm_draft: Any | None = None,
) -> int:
    """Resolved step/row count for strategy selector (not raw draft trait bullets)."""
    if semantic_shape == "comparison" and comparison is not None:
        if comparison.rows:
            return max(len(comparison.rows), 3)
        paired = len(comparison.left_traits) + len(comparison.right_traits)
        return max(paired, 3)

    if semantic_shape == "linear_process":
        if process_llm_draft is not None and getattr(process_llm_draft, "steps", None):
            return len(process_llm_draft.steps)
        rag_steps, _ = extract_process_steps_from_rag(rag_context, concept)
        if len(rag_steps) >= 3:
            return len(rag_steps)
        if draft.traits:
            filtered, _ = filter_process_trait_steps(list(draft.traits), concept=concept)
            if len(filtered) >= 3:
                return len(filtered)
        return 3

    if semantic_shape == "cycle":
        if len(draft.traits) >= 3:
            return min(len(draft.traits), 8)
        return 4

    return len(draft.traits)


def process_steps_for_shape(
    *,
    shape: SemanticShape,
    draft: AuthoringSemanticDraft,
    comparison: ComparisonSidesDraft | None,
    rag_context: str | None,
    concept: str,
) -> tuple[TraitDraft, ...]:
    """Ordered steps for cycle / linear builders (3–8)."""
    if shape == "comparison" and comparison is not None:
        return comparison.left_traits + comparison.right_traits
    steps = list(draft.traits)
    if shape == "cycle":
        if len(steps) < 3:
            steps = list(_default_cycle_steps(concept))
        elif "water" in _text_blob(draft.topic_label, concept) and len(steps) < 4:
            steps = [
                TraitDraft(
                    label="Evaporation",
                    summary="Water rises as vapor.",
                    narration="Warmth turns water into vapor.",
                    kind="process",
                ),
                TraitDraft(
                    label="Condensation",
                    summary="Vapor forms clouds.",
                    narration="Vapor cools and forms clouds.",
                    kind="process",
                ),
                TraitDraft(
                    label="Precipitation",
                    summary="Water falls as rain or snow.",
                    narration="Clouds release water.",
                    kind="process",
                ),
                TraitDraft(
                    label="Collection",
                    summary="Water gathers in bodies.",
                    narration="Water collects in lakes and oceans.",
                    kind="process",
                ),
            ]
        elif "butterfly" in _text_blob(draft.topic_label, concept) and len(steps) < 4:
            steps = [
                TraitDraft(
                    label="Egg",
                    summary="A butterfly starts as an egg.",
                    narration="The life cycle begins with an egg.",
                    kind="process",
                ),
                TraitDraft(
                    label="Larva",
                    summary="The caterpillar hatches and eats.",
                    narration="The larva grows by feeding.",
                    kind="process",
                ),
                TraitDraft(
                    label="Pupa",
                    summary="The caterpillar forms a chrysalis.",
                    narration="Inside the pupa, the body transforms.",
                    kind="process",
                ),
                TraitDraft(
                    label="Adult",
                    summary="The adult butterfly emerges.",
                    narration="The adult can fly and reproduce.",
                    kind="process",
                ),
            ]
    if shape == "linear_process":
        rag_steps, _rag_stats = extract_process_steps_from_rag(rag_context, concept)
        if len(rag_steps) >= 3:
            steps = list(rag_steps)
        elif steps:
            steps, _ = filter_process_trait_steps(steps, concept=concept)
        if len(steps) < 3 and draft.traits:
            steps, _ = filter_process_trait_steps(draft.traits, concept=concept)
        if len(steps) < 3:
            steps = list(_default_linear_process_steps(concept))
    cap = CIR_V1_MAX_NODES if shape == "linear_process" else 8
    steps = steps[:cap]
    if len(steps) < 3:
        fallback = _default_linear_process_steps(concept) if shape == "linear_process" else _default_cycle_steps(concept)
        steps = list(fallback)[: min(4, cap)]
    return tuple(steps[:cap])


def process_steps_for_cycle_with_stats(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
    process_llm_draft: Any | None = None,
    process_llm_debug: dict[str, Any] | None = None,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats, Any, str]:
    """
    Cycle ring steps: authored process_llm_draft primary, deterministic fallback.

    Mirrors ``process_steps_for_linear_with_stats`` but routes through the
    cycle-specific resolver (capped at 7 stages, ring-aware narration).
    """
    from app.vtse.authoring.process_authoring import resolve_cycle_process_authoring

    return resolve_cycle_process_authoring(
        draft=draft,
        rag_context=rag_context,
        concept=concept,
        process_llm_draft=process_llm_draft,
        process_llm_debug=process_llm_debug,
    )


def process_steps_for_linear_with_stats(
    *,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    concept: str,
    process_llm_draft: Any | None = None,
    process_llm_debug: dict[str, Any] | None = None,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats, Any, str]:
    """Linear process steps: authored process_llm_draft primary, deterministic RAG fallback."""
    from app.vtse.authoring.process_authoring import resolve_linear_process_authoring

    return resolve_linear_process_authoring(
        draft=draft,
        rag_context=rag_context,
        concept=concept,
        process_llm_draft=process_llm_draft,
        process_llm_debug=process_llm_debug,
    )
