"""Hierarchy semantic draft schema + validation (authored / structured payloads)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HIERARCHY_LLM_MIN_TRAITS = 3
HIERARCHY_LLM_MAX_TRAITS = 6

_QUESTION_START_RE = re.compile(
    r"^(what|can|why|how|is|are|when|which|does|do|did|will|could|should|would)\b",
    re.IGNORECASE,
)
_QUESTION_END_RE = re.compile(r"\?$")


@dataclass(frozen=True)
class HierarchyTraitSemanticV1:
    """One validated hierarchy branch — strict role separation."""

    concise_node_label: str
    explanation_text: str
    narration_text: str


@dataclass(frozen=True)
class HierarchyLLMDraftV1:
    """Validated hierarchy semantic draft."""

    topic: str
    anchor_label: str
    traits: tuple[HierarchyTraitSemanticV1, ...]
    hierarchy_semantic_confidence: float


def _is_question_label(text: str) -> bool:
    t = text.strip()
    return bool(_QUESTION_START_RE.match(t) or _QUESTION_END_RE.search(t))


def _is_sentence_fragment(text: str) -> bool:
    """True when the label looks like a sentence fragment (too many words or contains verbs)."""
    words = text.strip().split()
    if len(words) > 6:
        return True
    low = text.strip().lower()
    fragment_markers = (
        " are things", " is a ", " is the ", " are a ", "things that",
        " can ", " will ", " have ", " do ", " does ",
    )
    return any(m in low for m in fragment_markers)


def _clean(text: str, *, max_len: int, fallback: str = "") -> str:
    from app.vtse.authoring.content_filters import (
        is_placeholder_text,
        is_practice_or_support_content,
        strip_scaffold_prefix,
    )
    cleaned = strip_scaffold_prefix((text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s*\.{2,}$", "", cleaned).strip()
    cleaned = cleaned.rstrip("\u2026").strip()
    if not cleaned or is_placeholder_text(cleaned) or is_practice_or_support_content(cleaned):
        return fallback
    return cleaned[:max_len]


def _compute_semantic_expansion_ratio(
    traits: list[HierarchyTraitSemanticV1],
    *,
    rag_context: str | None,
) -> float:
    rag_lines = [
        ln.strip()
        for ln in (rag_context or "").replace("\r", "").split("\n")
        if len(ln.strip()) >= 10
    ]
    rag_avg = sum(len(ln) for ln in rag_lines) / max(len(rag_lines), 1)
    expl_avg = sum(len(t.explanation_text) for t in traits) / max(len(traits), 1)
    return round(expl_avg / max(rag_avg, 1.0), 2)


def validate_hierarchy_llm_draft(
    payload: dict[str, Any] | None,
    *,
    rag_context: str | None = None,
) -> tuple[HierarchyLLMDraftV1 | None, dict[str, Any]]:
    """Validate structured JSON against hierarchy semantic contract."""
    debug: dict[str, Any] = {
        "validation_rejected_traits": 0,
        "question_label_rejected": 0,
        "sentence_fragment_rejected": 0,
    }
    if not payload or not isinstance(payload, dict):
        debug["validation_failure_reason"] = "empty_payload"
        return None, debug

    topic = _clean(
        str(payload.get("topic") or ""),
        max_len=120,
        fallback="Concept",
    )
    anchor_raw = str(payload.get("anchor_label") or "")
    anchor_label = _clean(anchor_raw, max_len=80, fallback=topic)
    confidence_raw = payload.get("hierarchy_semantic_confidence")
    try:
        confidence = float(confidence_raw or 0.7)
    except (ValueError, TypeError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    raw_traits = payload.get("traits")
    if not isinstance(raw_traits, list):
        debug["validation_failure_reason"] = "missing_traits_array"
        return None, debug

    traits: list[HierarchyTraitSemanticV1] = []
    for item in raw_traits[:HIERARCHY_LLM_MAX_TRAITS]:
        if not isinstance(item, dict):
            debug["validation_rejected_traits"] = int(debug["validation_rejected_traits"]) + 1
            continue

        raw_label = str(
            item.get("concise_node_label") or item.get("label") or ""
        ).strip()
        node_label = _clean(raw_label, max_len=48, fallback="")

        if not node_label or len(node_label) < 2:
            debug["validation_rejected_traits"] = int(debug["validation_rejected_traits"]) + 1
            continue

        if _is_question_label(node_label):
            debug["validation_rejected_traits"] = int(debug["validation_rejected_traits"]) + 1
            debug["question_label_rejected"] = int(debug["question_label_rejected"]) + 1
            continue

        if _is_sentence_fragment(node_label):
            words = node_label.split()
            node_label = " ".join(words[:4])
            debug["sentence_fragment_rejected"] = int(debug["sentence_fragment_rejected"]) + 1

        if len(node_label.split()) > 6:
            debug["validation_rejected_traits"] = int(debug["validation_rejected_traits"]) + 1
            continue

        explanation = _clean(
            str(item.get("explanation_text") or item.get("explanation") or item.get("summary") or ""),
            max_len=600,
            fallback="",
        )
        narration = _clean(
            str(item.get("narration_text") or item.get("narration") or ""),
            max_len=400,
            fallback=explanation[:200] if explanation else f"Consider how {node_label.lower()} matters.",
        )

        if not explanation or len(explanation) < 8:
            debug["validation_rejected_traits"] = int(debug["validation_rejected_traits"]) + 1
            continue

        traits.append(
            HierarchyTraitSemanticV1(
                concise_node_label=node_label,
                explanation_text=explanation,
                narration_text=narration,
            )
        )

    if len(traits) < HIERARCHY_LLM_MIN_TRAITS:
        debug["validation_failure_reason"] = f"too_few_traits_{len(traits)}"
        return None, debug

    draft = HierarchyLLMDraftV1(
        topic=topic,
        anchor_label=anchor_label,
        traits=tuple(traits),
        hierarchy_semantic_confidence=confidence,
    )
    debug["hierarchy_llm_traits_generated"] = len(traits)
    debug["hierarchy_authoring_mode"] = "llm"
    debug["hierarchy_semantic_confidence"] = confidence
    if rag_context:
        debug["hierarchy_semantic_expansion_ratio"] = _compute_semantic_expansion_ratio(
            traits, rag_context=rag_context
        )
    return draft, debug
