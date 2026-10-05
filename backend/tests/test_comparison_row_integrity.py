"""Comparison row integrity validation tests."""

from __future__ import annotations

from app.vtse.authoring.comparison_rows import (
    ComparisonRow,
    build_comparison_rows,
    is_complete_comparison_row,
    validate_comparison_rows,
)
from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.authoring.semantic_extract import TraitDraft


def test_validate_comparison_rows_rejects_orphans() -> None:
    rows = [
        ComparisonRow(
            dimension="Energy",
            left_title="Food",
            left_detail="Humans need food.",
            right_title="",
            right_detail="",
        ),
        ComparisonRow(
            dimension="Growth",
            left_title="Grows",
            left_detail="Living things grow.",
            right_title="No growth",
            right_detail="Non-living things do not grow.",
        ),
    ]
    complete, stats = validate_comparison_rows(rows, left_label="Humans", right_label="Robots")
    assert len(complete) == 1
    assert stats.skipped_incomplete_rows == 1
    assert stats.orphan_row_count == 1


def test_build_comparison_rows_only_complete_pairs() -> None:
    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="compare",
        anchor_label="Humans",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    rows, stats = build_comparison_rows(
        left_label="Humans",
        right_label="Robots",
        concept="compare",
        draft=draft,
        rag_context="- Robots need electricity only on robot side",
    )
    assert len(rows) >= 2
    assert all(is_complete_comparison_row(r) for r in rows)
    assert stats.skipped_incomplete_rows >= 0


def test_right_beat_narration_suppressed() -> None:
    sides = ComparisonSidesDraft(
        left_label="Humans",
        right_label="Robots",
        left_traits=(
            TraitDraft("Energy", "Humans need food.", "Humans need food."),
        ),
        right_traits=(
            TraitDraft("Power", "Robots need electricity.", "Robots need electricity."),
        ),
    )
    plan = build_comparison_contrast_plan(
        topic_label="Humans vs Robots",
        sides=sides,
        concept_id="compare",
    )
    row_beats = [
        b for b in plan.beats if b.metadata.get("comparison_side") in ("left", "right")
    ]
    assert len(row_beats) == 2
    left_beat = next(b for b in row_beats if b.metadata.get("comparison_side") == "left")
    right_beat = next(b for b in row_beats if b.metadata.get("comparison_side") == "right")
    assert "in contrast" in (left_beat.narration_text or "").lower()
    assert (right_beat.narration_text or "").strip() in ("", "\u200b")
    assert right_beat.metadata.get("narration_owner") == "comparison_row_suppressed"


def test_rejects_same_side_robot_only_rows() -> None:
    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="compare",
        anchor_label="Humans",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    rag = (
        "- Robots are machines created by humans, while they do not have real emotions\n"
        "- Humans need food, water, and rest to survive\n"
        "- Robots need electricity or power sources to operate\n"
        "- Humans need food while robots need electricity"
    )
    rows, stats = build_comparison_rows(
        left_label="Humans",
        right_label="Robots",
        concept="compare",
        draft=draft,
        rag_context=rag,
    )
    assert len(rows) >= 2
    for row in rows:
        assert row.dimension.lower() not in ("humans", "robots")
        assert "human" in row.left_detail.lower() or "food" in row.left_detail.lower() or "survive" in row.left_detail.lower()
        assert "robot" in row.right_detail.lower() or "electric" in row.right_detail.lower()
    assert not any(
        "robot" in row.left_detail.lower() and "human" not in row.left_detail.lower()
        and "robot" in row.right_detail.lower()
        for row in rows
    )
