"""Hierarchy Phase A — semantic extraction hygiene (filters, dedupe, observability)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.vtse.authoring.content_filters import (
    is_authoring_scaffold_header,
    is_placeholder_text,
    is_practice_or_support_content,
    is_question_text,
    strip_scaffold_prefix,
)

if TYPE_CHECKING:
    from app.vtse.authoring.semantic_extract import TraitDraft

_EXCLUDE_REASON_PLACEHOLDER = "placeholder"
_EXCLUDE_REASON_PRACTICE = "practice"
_EXCLUDE_REASON_SCAFFOLD = "scaffold"
_EXCLUDE_REASON_TOO_SHORT = "too_short"


@dataclass(frozen=True)
class HierarchyExtractionHygiene:
    """Counters for hierarchy semantic cleanup (surfaced in ``cir_instruction_debug``)."""

    hierarchy_placeholder_filtered: int = 0
    hierarchy_practice_nodes_filtered: int = 0
    hierarchy_duplicate_nodes_removed: int = 0
    hierarchy_semantic_groups_created: int = 0
    hierarchy_raw_trait_count: int = 0
    hierarchy_final_trait_count: int = 0

    def to_debug_dict(self) -> dict[str, int]:
        return {
            "hierarchy_placeholder_filtered": self.hierarchy_placeholder_filtered,
            "hierarchy_practice_nodes_filtered": self.hierarchy_practice_nodes_filtered,
            "hierarchy_duplicate_nodes_removed": self.hierarchy_duplicate_nodes_removed,
            "hierarchy_semantic_groups_created": self.hierarchy_semantic_groups_created,
            "hierarchy_raw_trait_count": self.hierarchy_raw_trait_count,
            "hierarchy_final_trait_count": self.hierarchy_final_trait_count,
        }


def normalize_semantic_key(text: str | None) -> str:
    """Case/whitespace/punctuation-normalized key for dedupe and anchor overlap checks."""
    cleaned = strip_scaffold_prefix(str(text or "").strip())
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.lower())
    return " ".join(cleaned.split())


def classify_excluded_authoring_line(text: str | None) -> str | None:
    """
    Return exclusion reason when a RAG/template line must not become a trait.

    ``None`` means the line may be used (caller may still require min length).
    """
    raw = (text or "").strip()
    if not raw:
        return _EXCLUDE_REASON_TOO_SHORT
    if is_practice_or_support_content(raw):
        return _EXCLUDE_REASON_PRACTICE
    if is_question_text(raw):
        return _EXCLUDE_REASON_PRACTICE
    if is_authoring_scaffold_header(raw):
        return _EXCLUDE_REASON_SCAFFOLD
    cleaned = strip_scaffold_prefix(raw)
    if is_placeholder_text(cleaned) or is_placeholder_text(raw):
        return _EXCLUDE_REASON_PLACEHOLDER
    if len(cleaned) < 3:
        return _EXCLUDE_REASON_TOO_SHORT
    return None


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def concise_trait_label_from_line(line: str, *, max_words: int = 5) -> str | None:
    """Prefer a short child label after scaffold strip (not full RAG sentence)."""
    cleaned = strip_scaffold_prefix(line.strip())
    if classify_excluded_authoring_line(cleaned):
        return None
    head = cleaned.split(":")[0].split(".")[0].strip()
    head = re.sub(r"\s+", " ", head)
    if not head or len(head) < 3:
        return None
    words = head.split()
    if len(words) > max_words:
        head = " ".join(words[:max_words])
    if classify_excluded_authoring_line(head):
        return None
    return _clip(head, 48)


def sanitize_trait_draft_fields(
    *,
    label: str,
    summary: str,
    narration: str,
    fallback_label: str,
):
    """Build a trait only when label/summary pass production filters."""
    from app.vtse.authoring.semantic_extract import TraitDraft
    clean_label = strip_scaffold_prefix(label.strip())
    clean_summary = strip_scaffold_prefix(summary.strip())
    clean_narration = strip_scaffold_prefix(narration.strip())

    if classify_excluded_authoring_line(clean_label):
        clean_label = ""
    if classify_excluded_authoring_line(clean_summary):
        clean_summary = ""
    if classify_excluded_authoring_line(clean_narration):
        clean_narration = ""

    if not clean_label or is_placeholder_text(clean_label):
        if clean_summary and not is_placeholder_text(clean_summary):
            clean_label = concise_trait_label_from_line(clean_summary) or ""
        if not clean_label:
            return None

    if is_placeholder_text(clean_label) or is_practice_or_support_content(clean_label):
        return None

    fb = _clip(fallback_label or "Key idea", 48)
    safe_label = _clip(clean_label, 80)
    safe_summary = _clip(
        clean_summary or safe_label,
        600,
    )
    if is_placeholder_text(safe_summary) or is_practice_or_support_content(safe_summary):
        safe_summary = safe_label

    safe_narration = _clip(
        clean_narration or f"Next, consider {safe_label.lower()}.",
        400,
    )
    if is_placeholder_text(safe_narration) or is_practice_or_support_content(safe_narration):
        safe_narration = _clip(f"Consider how {safe_label.lower()} relates to the main idea.", 400)

    return TraitDraft(
        label=safe_label,
        summary=safe_summary,
        narration=safe_narration,
        kind="property",
    )


def trait_overlaps_anchor(
    trait: "TraitDraft",
    *,
    anchor_label: str,
    concept_label: str,
) -> bool:
    """
    True when a child trait label repeats the root/anchor concept.

    Summary/narration may mention the parent concept; only the card label is
    used for deduplication so distinct traits (e.g. Grow, Breathe) are kept.
    """
    anchor_key = normalize_semantic_key(anchor_label)
    concept_key = normalize_semantic_key(concept_label)
    keys_to_check = {k for k in (anchor_key, concept_key) if k}
    if not keys_to_check:
        return False

    label_key = normalize_semantic_key(trait.label)
    if not label_key or len(label_key) < 3:
        return False

    for root_key in keys_to_check:
        if label_key == root_key:
            return True
        if len(root_key) >= 4 and label_key.startswith(root_key + " "):
            extra = label_key[len(root_key) :].strip().split()
            if len(extra) <= 2:
                return True
    return False


def _dedupe_near_duplicate_traits(traits: list["TraitDraft"]) -> tuple[list["TraitDraft"], int]:
    """Collapse near-duplicate traits; prefer the more concise label."""
    removed = 0
    out: list[TraitDraft] = []
    keys: list[str] = []

    for trait in traits:
        key = normalize_semantic_key(trait.label)
        if not key:
            removed += 1
            continue

        merged = False
        for i, existing_key in enumerate(keys):
            if key == existing_key:
                merged = True
                break
            if key.startswith(existing_key + " ") or existing_key.startswith(key + " "):
                if len(key) < len(existing_key):
                    out[i] = trait
                    keys[i] = key
                merged = True
                break

        if merged:
            removed += 1
        else:
            out.append(trait)
            keys.append(key)

    return out, removed


def apply_hierarchy_trait_hygiene(
    traits: list["TraitDraft"],
    *,
    anchor_label: str,
    concept_label: str,
    hygiene: HierarchyExtractionHygiene,
) -> tuple[tuple[TraitDraft, ...], HierarchyExtractionHygiene]:
    """
    Anchor/trait dedupe and near-duplicate collapse.

    Updates ``hygiene`` duplicate count and final trait count.
    """
    deduped: list[TraitDraft] = []
    anchor_removed = 0
    for trait in traits:
        if trait_overlaps_anchor(trait, anchor_label=anchor_label, concept_label=concept_label):
            anchor_removed += 1
            continue
        deduped.append(trait)

    collapsed, near_dup_removed = _dedupe_near_duplicate_traits(deduped)
    final = tuple(collapsed[:6])
    groups = 1 + len(final)  # 1 anchor/root group + trait children

    return final, HierarchyExtractionHygiene(
        hierarchy_placeholder_filtered=hygiene.hierarchy_placeholder_filtered,
        hierarchy_practice_nodes_filtered=hygiene.hierarchy_practice_nodes_filtered,
        hierarchy_duplicate_nodes_removed=(
            hygiene.hierarchy_duplicate_nodes_removed
            + anchor_removed
            + near_dup_removed
        ),
        hierarchy_semantic_groups_created=groups,
        hierarchy_raw_trait_count=hygiene.hierarchy_raw_trait_count,
        hierarchy_final_trait_count=len(final),
    )


def record_line_exclusion(hygiene: HierarchyExtractionHygiene, reason: str) -> HierarchyExtractionHygiene:
    if reason == _EXCLUDE_REASON_PLACEHOLDER or reason == _EXCLUDE_REASON_SCAFFOLD:
        return HierarchyExtractionHygiene(
            hierarchy_placeholder_filtered=hygiene.hierarchy_placeholder_filtered + 1,
            hierarchy_practice_nodes_filtered=hygiene.hierarchy_practice_nodes_filtered,
            hierarchy_duplicate_nodes_removed=hygiene.hierarchy_duplicate_nodes_removed,
            hierarchy_semantic_groups_created=hygiene.hierarchy_semantic_groups_created,
            hierarchy_raw_trait_count=hygiene.hierarchy_raw_trait_count,
            hierarchy_final_trait_count=hygiene.hierarchy_final_trait_count,
        )
    if reason == _EXCLUDE_REASON_PRACTICE:
        return HierarchyExtractionHygiene(
            hierarchy_placeholder_filtered=hygiene.hierarchy_placeholder_filtered,
            hierarchy_practice_nodes_filtered=hygiene.hierarchy_practice_nodes_filtered + 1,
            hierarchy_duplicate_nodes_removed=hygiene.hierarchy_duplicate_nodes_removed,
            hierarchy_semantic_groups_created=hygiene.hierarchy_semantic_groups_created,
            hierarchy_raw_trait_count=hygiene.hierarchy_raw_trait_count,
            hierarchy_final_trait_count=hygiene.hierarchy_final_trait_count,
        )
    return hygiene


def filter_rag_lines_for_hierarchy(lines: list[str]) -> tuple[list[str], HierarchyExtractionHygiene]:
    """Filter RAG lines before trait construction."""
    hygiene = HierarchyExtractionHygiene()
    kept: list[str] = []
    for line in lines:
        reason = classify_excluded_authoring_line(line)
        if reason:
            hygiene = record_line_exclusion(hygiene, reason)
            continue
        kept.append(strip_scaffold_prefix(line))
    return kept, hygiene
