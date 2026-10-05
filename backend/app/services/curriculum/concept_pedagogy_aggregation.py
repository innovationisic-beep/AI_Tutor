"""Aggregate concept-level study points / learning outcomes for cluster pedagogy."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple


def _clean_bullets(values: Iterable[str] | None) -> List[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def aggregate_concept_pedagogy_bullets(
    concepts: Sequence[object],
    *,
    order_by_sort_order: bool = False,
) -> Tuple[List[str], List[str]]:
    """
    Aggregate study_points and learning_outcomes from concepts.

    By default preserves caller-provided order (session teaching order /
    ``list_by_cluster`` sort). Pass ``order_by_sort_order=True`` only when
    the input sequence is unordered and concept ``sort_order`` is authoritative.

    Exact duplicate strings are removed while preserving first-seen order.
    """
    study: List[str] = []
    outcomes: List[str] = []
    if order_by_sort_order:
        ordered: Sequence[object] = sorted(
            concepts,
            key=lambda c: (
                int(getattr(c, "sort_order", 0) or 0),
                str(getattr(c, "id", "") or ""),
            ),
        )
    else:
        ordered = concepts
    for concept in ordered:
        study.extend(_clean_bullets(getattr(concept, "study_points", None)))
        outcomes.extend(_clean_bullets(getattr(concept, "learning_outcomes", None)))
    return _dedupe_preserve_order(study), _dedupe_preserve_order(outcomes)
