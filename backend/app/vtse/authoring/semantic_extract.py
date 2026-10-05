"""Deterministic semantic extraction for Zone 1 authoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.vtse.authoring.hierarchy_semantic_hygiene import (
    HierarchyExtractionHygiene,
    apply_hierarchy_trait_hygiene,
    classify_excluded_authoring_line,
    concise_trait_label_from_line,
    filter_rag_lines_for_hierarchy,
    normalize_semantic_key,
    record_line_exclusion,
    sanitize_trait_draft_fields,
    trait_overlaps_anchor,
)


@dataclass(frozen=True)
class TraitDraft:
    """One teachable trait / characteristic."""

    label: str
    summary: str
    narration: str
    kind: str = "property"


@dataclass(frozen=True)
class AuthoringSemanticDraft:
    """Normalized input for strategy builders."""

    topic_label: str
    concept_label: str
    anchor_label: str
    anchor_summary: str
    anchor_narration: str
    traits: tuple[TraitDraft, ...]
    source: str
    hierarchy_hygiene: HierarchyExtractionHygiene | None = None


_BULLET_RE = re.compile(r"^[\s]*(?:[-*•]|\d+[.)])\s+(.+)$", re.MULTILINE)


def _slug_token(text: str, max_len: int = 32) -> str:
    t = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (t[:max_len] if t else "item")


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _lines_from_rag(
    rag_context: str | None,
    *,
    limit: int | None = None,
    max_line_chars: int | None = None,
) -> list[str]:
    from app.cir.limits import RAG_INGEST_LINE_LIMIT, RAG_INGEST_LINE_MAX_CHARS

    line_limit = RAG_INGEST_LINE_LIMIT if limit is None else limit
    line_chars = RAG_INGEST_LINE_MAX_CHARS if max_line_chars is None else max_line_chars
    if not rag_context or not str(rag_context).strip():
        return []
    out: list[str] = []
    for raw in str(rag_context).replace("\r", "").split("\n"):
        t = raw.strip()
        if len(t) < 10:
            continue
        if t.startswith("#"):
            continue
        m = _BULLET_RE.match(t)
        line = m.group(1).strip() if m else t
        min_len = 3 if m else 10
        if len(line) >= min_len:
            out.append(_clip(line, line_chars))
        if len(out) >= line_limit:
            break
    return out


def _trait_from_template_step(
    step: dict[str, Any],
    *,
    concept_label: str,
    hygiene: HierarchyExtractionHygiene,
) -> tuple[TraitDraft | None, HierarchyExtractionHygiene]:
    title = _clip(str(step.get("title") or step.get("label") or ""), 80)
    ann = _clip(str(step.get("annotation") or step.get("summary") or title), 600)
    narr = _clip(
        str(step.get("narration") or step.get("narration_text") or f"Next, {title}."),
        400,
    )
    combined = " ".join(p for p in (title, ann, narr) if p).strip()
    reason = classify_excluded_authoring_line(combined) or classify_excluded_authoring_line(title)
    if reason:
        return None, record_line_exclusion(hygiene, reason)
    trait = sanitize_trait_draft_fields(
        label=title,
        summary=ann,
        narration=narr,
        fallback_label=concept_label,
    )
    if trait is None:
        reason = classify_excluded_authoring_line(title) or "placeholder"
        return None, record_line_exclusion(hygiene, reason)
    return trait, hygiene


def _trait_from_rag_line(
    line: str,
    *,
    concept_label: str,
    hygiene: HierarchyExtractionHygiene,
) -> tuple[TraitDraft | None, HierarchyExtractionHygiene]:
    reason = classify_excluded_authoring_line(line)
    if reason:
        return None, record_line_exclusion(hygiene, reason)
    short_label = concise_trait_label_from_line(line)
    if not short_label:
        return None, record_line_exclusion(hygiene, "placeholder")
    trait = sanitize_trait_draft_fields(
        label=short_label,
        summary=_clip(line, 200),
        narration=_clip(
            f"Consider how {short_label.lower()} relates to {concept_label}.",
            400,
        ),
        fallback_label=short_label,
    )
    if trait is None:
        return None, record_line_exclusion(hygiene, "placeholder")
    return trait, hygiene


def extract_authoring_semantics(
    *,
    topic_name: str,
    concept: str,
    rag_context: str | None = None,
    trait_steps: list[dict[str, Any]] | None = None,
    source: str = "deterministic_extract",
    opening_narration: str = "",
) -> AuthoringSemanticDraft:
    """
    Build stable trait drafts from RAG lines, explicit steps, or concept defaults.

    Applies hierarchy Phase A hygiene: placeholder/practice/scaffold filters,
    anchor/trait dedupe, and near-duplicate collapse.

    ``trait_steps`` items may include title, annotation, narration (planner template shape).
    """
    concept_label = _clip((concept or "").strip() or (topic_name or "").strip() or "Main concept", 80)
    topic_label = _clip((topic_name or "").strip() or concept_label, 120)

    hygiene = HierarchyExtractionHygiene()
    traits: list[TraitDraft] = []
    raw_count = 0

    if trait_steps:
        for step in trait_steps[:8]:
            if not isinstance(step, dict):
                continue
            raw_count += 1
            trait, hygiene = _trait_from_template_step(
                step,
                concept_label=concept_label,
                hygiene=hygiene,
            )
            if trait is not None:
                traits.append(trait)

    if not traits:
        raw_lines = _lines_from_rag(rag_context)
        filtered_lines, line_hygiene = filter_rag_lines_for_hierarchy(raw_lines)
        hygiene = HierarchyExtractionHygiene(
            hierarchy_placeholder_filtered=hygiene.hierarchy_placeholder_filtered
            + line_hygiene.hierarchy_placeholder_filtered,
            hierarchy_practice_nodes_filtered=hygiene.hierarchy_practice_nodes_filtered
            + line_hygiene.hierarchy_practice_nodes_filtered,
            hierarchy_duplicate_nodes_removed=hygiene.hierarchy_duplicate_nodes_removed,
            hierarchy_semantic_groups_created=hygiene.hierarchy_semantic_groups_created,
            hierarchy_raw_trait_count=hygiene.hierarchy_raw_trait_count,
            hierarchy_final_trait_count=hygiene.hierarchy_final_trait_count,
        )
        for line in filtered_lines[:8]:
            raw_count += 1
            trait, hygiene = _trait_from_rag_line(
                line,
                concept_label=concept_label,
                hygiene=hygiene,
            )
            if trait is not None:
                traits.append(trait)

    hygiene = HierarchyExtractionHygiene(
        hierarchy_placeholder_filtered=hygiene.hierarchy_placeholder_filtered,
        hierarchy_practice_nodes_filtered=hygiene.hierarchy_practice_nodes_filtered,
        hierarchy_duplicate_nodes_removed=hygiene.hierarchy_duplicate_nodes_removed,
        hierarchy_semantic_groups_created=hygiene.hierarchy_semantic_groups_created,
        hierarchy_raw_trait_count=raw_count,
        hierarchy_final_trait_count=hygiene.hierarchy_final_trait_count,
    )

    anchor_label = concept_label
    anchor_summary = _clip(f"Central idea for {topic_label}", 200)
    provided_opening = _clip(opening_narration, 400)
    anchor_narration = provided_opening or _clip(
        f"Let us anchor the idea first: {concept_label} brings these ideas together.",
        400,
    )

    final_traits, hygiene = apply_hierarchy_trait_hygiene(
        traits,
        anchor_label=anchor_label,
        concept_label=concept_label,
        hygiene=hygiene,
    )

    if len(final_traits) < 3:
        pass  # Never pad with domain-specific defaults; hierarchy LLM or caller supplies traits.

    final_traits = final_traits[:6]

    return AuthoringSemanticDraft(
        topic_label=topic_label,
        concept_label=concept_label,
        anchor_label=anchor_label,
        anchor_summary=anchor_summary,
        anchor_narration=anchor_narration,
        traits=final_traits,
        source=source,
        hierarchy_hygiene=hygiene,
    )
