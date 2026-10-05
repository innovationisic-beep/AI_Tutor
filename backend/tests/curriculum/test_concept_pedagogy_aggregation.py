"""Unit tests for concept pedagogy bullet aggregation."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.curriculum.concept_pedagogy_aggregation import (
    aggregate_concept_pedagogy_bullets,
)


def test_aggregate_empty_concepts():
    study, outcomes = aggregate_concept_pedagogy_bullets([])
    assert study == []
    assert outcomes == []


def test_aggregate_orders_by_sort_order_and_dedupes():
    concepts = [
        SimpleNamespace(
            id="b",
            sort_order=2,
            study_points=["B study", "Shared"],
            learning_outcomes=["B out"],
        ),
        SimpleNamespace(
            id="a",
            sort_order=1,
            study_points=["A study", "Shared"],
            learning_outcomes=["A out", "B out"],
        ),
        SimpleNamespace(
            id="c",
            sort_order=3,
            study_points=["  ", "C study"],
            learning_outcomes=[],
        ),
    ]
    study, outcomes = aggregate_concept_pedagogy_bullets(
        concepts, order_by_sort_order=True
    )
    assert study == ["A study", "Shared", "B study", "C study"]
    assert outcomes == ["A out", "B out"]


def test_aggregate_preserves_caller_order_for_session_boundary():
    """Session teaching order may span clusters; do not re-sort by sort_order."""
    concepts = [
        SimpleNamespace(
            id="z2",
            sort_order=0,
            study_points=["Later cluster first concept"],
            learning_outcomes=["Out Z"],
        ),
        SimpleNamespace(
            id="a1",
            sort_order=5,
            study_points=["Earlier cluster concept"],
            learning_outcomes=["Out A"],
        ),
    ]
    study, outcomes = aggregate_concept_pedagogy_bullets(concepts)
    assert study == ["Later cluster first concept", "Earlier cluster concept"]
    assert outcomes == ["Out Z", "Out A"]


def test_aggregate_single_concept():
    concepts = [
        SimpleNamespace(
            id="1",
            sort_order=0,
            study_points=["Only study"],
            learning_outcomes=["Only outcome"],
        )
    ]
    study, outcomes = aggregate_concept_pedagogy_bullets(concepts)
    assert study == ["Only study"]
    assert outcomes == ["Only outcome"]
