"""Comparison row authoring — dimension-aligned pairing."""

from __future__ import annotations

from app.vtse.authoring.comparison_rows import (
    build_comparison_rows,
    is_placeholder_text,
    structured_row_narration,
)
from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft, TraitDraft
from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan


def test_contrast_line_parsing() -> None:
    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="humans and robots",
        anchor_label="Humans",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    rag = "- Emotions: humans feel joy while robots follow programming"
    rows, stats = build_comparison_rows(
        left_label="Humans",
        right_label="Robots",
        concept="comparison",
        draft=draft,
        rag_context=rag,
    )
    assert len(rows) >= 1
    assert stats.narration_mode == "comparison_teacher_expanded"
    assert "emotion" in rows[0].dimension.lower() or "humans" in rows[0].left_detail.lower()


def test_side_bucket_rag_pairing() -> None:
    draft = AuthoringSemanticDraft(
        topic_label="Plant Cell vs Animal Cell",
        concept_label="cells",
        anchor_label="Plant Cell",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    rag = (
        "- Chloroplasts in plant cells\n"
        "- Centrioles in animal cells\n"
        "- Cell wall in plant cells"
    )
    rows, _ = build_comparison_rows(
        left_label="Plant Cell",
        right_label="Animal Cell",
        concept="cells",
        draft=draft,
        rag_context=rag,
    )
    assert len(rows) >= 2
    assert all(row.left_title and row.right_title for row in rows)
    assert all(len(row.left_title.split()) <= 4 for row in rows)


def test_short_labels_not_full_sentences_in_plan() -> None:
    sides = ComparisonSidesDraft(
        left_label="Humans",
        right_label="Robots",
        left_traits=(
            TraitDraft("Emotions", "Humans have emotions.", "Humans have emotions."),
            TraitDraft("Energy", "Humans need food.", "Humans need food."),
        ),
        right_traits=(
            TraitDraft("No emotions", "Robots do not have emotions.", "Robots do not have emotions."),
            TraitDraft("Electricity", "Robots need electricity.", "Robots need electricity."),
        ),
    )
    plan = build_comparison_contrast_plan(
        topic_label="Humans vs Robots",
        sides=sides,
        concept_id="comparison",
    )
    row_nodes = [n for n in plan.semantic_graph.nodes if n.semantic_role == "comparison_row"]
    assert row_nodes
    assert all(len(n.label.split()) <= 4 for n in row_nodes)
    assert plan.provenance["comparison_authoring"]["narration_mode"] == "comparison_teacher_expanded"


def test_structured_narration_style() -> None:
    text = structured_row_narration(
        dimension="Emotions",
        left_label="Humans",
        right_label="Robots",
        left_detail="Humans have emotions",
        right_detail="Robots do not have emotions",
        focus="pair",
    )
    assert "while" in text.lower()
    assert "emotions" in text.lower()


def test_placeholder_filtered() -> None:
    assert is_placeholder_text("[Detailed — concept]")
    assert is_placeholder_text("concept a")
    draft = AuthoringSemanticDraft(
        topic_label="A vs B",
        concept_label="x",
        anchor_label="A",
        anchor_summary="",
        anchor_narration="",
        traits=(
            TraitDraft("[Detailed — concept]", "[Detailed — concept]", "[Detailed — concept]"),
        ),
        source="test",
    )
    rows, stats = build_comparison_rows(
        left_label="A",
        right_label="B",
        concept="x",
        draft=draft,
        rag_context="[Detailed — concept]",
    )
    assert len(rows) >= 2
    assert stats.placeholder_filtered >= 1
    assert all("[Detailed" not in row.left_detail for row in rows)


def test_llm_rows_not_padded_by_rag_extract() -> None:
    """Authored/LLM row count must win even when rag_context would extract more."""
    from app.vtse.authoring.comparison_rows import ComparisonRow

    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="compare",
        anchor_label="Humans",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="authored_vtse_template",
    )
    llm_rows = (
        ComparisonRow(
            dimension="Living",
            left_title="Alive",
            left_detail="Humans are living organisms.",
            right_title="Not alive",
            right_detail="Robots are non-living machines.",
        ),
        ComparisonRow(
            dimension="Growth",
            left_title="Can grow",
            left_detail="Humans grow over time.",
            right_title="No growth",
            right_detail="Robots do not grow biologically.",
        ),
    )
    # Outline-as-RAG (same content + an extra contrast) must not add a 3rd row.
    rag = (
        "- Living: humans are living organisms while robots are non-living machines\n"
        "- Growth: humans grow over time while robots do not grow biologically\n"
        "- Emotions: humans feel joy while robots follow programming\n"
        "- Energy: humans need food while robots need electricity"
    )
    rows, stats = build_comparison_rows(
        left_label="Humans",
        right_label="Robots",
        concept="compare",
        draft=draft,
        rag_context=rag,
        llm_rows=llm_rows,
    )
    assert len(rows) == 2
    assert [r.dimension for r in rows] == ["Living", "Growth"]
    assert stats.narration_detail_level == "llm_primary"
    assert stats.comparison_dimension_count == 2
