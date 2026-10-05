"""Pedagogical depth expansion tests for comparison authoring."""

from __future__ import annotations

from app.cir.limits import CIR_V1_MAX_NODES, COMPARISON_MAX_ROW_PAIRS, RAG_INGEST_LINE_MAX_CHARS
from app.vtse.authoring.comparison_rows import (
    ComparisonRow,
    build_comparison_rows,
    teacher_pair_narration,
)
from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft, _lines_from_rag
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
from app.vtse.strategies.common import CIR_MAX_NODES


def test_cir_capacity_supports_ten_comparison_rows() -> None:
    assert CIR_MAX_NODES >= 22
    assert (CIR_MAX_NODES - 2) // 2 >= COMPARISON_MAX_ROW_PAIRS


def test_rag_ingest_reads_longer_lines() -> None:
    long_line = "Humans " + ("need nutrients and rest " * 30)
    lines = _lines_from_rag(f"- {long_line}", limit=5)
    assert lines
    assert len(lines[0]) > 200
    assert len(lines[0]) <= RAG_INGEST_LINE_MAX_CHARS


def test_teacher_narration_richer_than_summary() -> None:
    text = teacher_pair_narration(
        dimension="Energy",
        left_label="Humans",
        right_label="Robots",
        left_detail="Humans need food and water because they are living organisms that require nutrients to survive.",
        right_detail="Robots need electricity or power sources because they are machines designed by humans.",
    )
    assert "while" not in text.lower()
    assert "in contrast" in text.lower()
    assert len(text) > 80


def test_build_many_rows_from_rag_bullets() -> None:
    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="compare",
        anchor_label="Humans",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    bullets = []
    for i in range(1, 5):
        bullets.append(f"- Humans trait {i}: humans need aspect {i} for survival")
        bullets.append(f"- Robots trait {i}: robots require power mode {i} to operate")
    rag = "\n".join(bullets)
    rows, stats = build_comparison_rows(
        left_label="Humans",
        right_label="Robots",
        concept="compare",
        draft=draft,
        rag_context=rag,
    )
    assert len(rows) >= 4
    assert stats.rag_lines_ingested >= 8
    assert stats.rag_context_chars_used > 0
    assert stats.narration_detail_level in (
        "deterministic_expanded",
        "deterministic_fallback",
        "llm_hybrid",
        "llm_primary",
    )


def test_plan_emits_up_to_max_row_pairs() -> None:
    rows = tuple(
        ComparisonRow(
            dimension=f"Dim{i}",
            left_title=f"L{i}",
            left_detail=f"Humans detail {i} with explanatory context.",
            right_title=f"R{i}",
            right_detail=f"Robots detail {i} with explanatory context.",
        )
        for i in range(8)
    )
    sides = ComparisonSidesDraft(
        left_label="Humans",
        right_label="Robots",
        rows=rows,
    )
    plan = build_comparison_contrast_plan(
        topic_label="Humans vs Robots",
        sides=sides,
        concept_id="compare",
    )
    row_nodes = [n for n in plan.semantic_graph.nodes if n.semantic_role == "comparison_row"]
    max_pairs = min(len(rows), (CIR_MAX_NODES - 2) // 2)
    assert len(row_nodes) == max_pairs * 2
    dbg = plan.provenance["comparison_authoring"]
    assert dbg["rows_rendered"] == max_pairs
    assert dbg["rows_clipped_by_budget"] == max(0, len(rows) - max_pairs)
    first_left = next(n for n in plan.semantic_graph.nodes if n.group == "left" and n.semantic_role == "comparison_row")
    assert len(first_left.narration) > 40
