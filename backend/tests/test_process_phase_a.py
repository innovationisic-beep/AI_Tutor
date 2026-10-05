"""Phase A tests for linear process / flow pedagogy cleanup."""

from __future__ import annotations

from app.vtse.authoring.content_filters import (
    is_authoring_scaffold_header,
    is_practice_or_support_content,
    sanitize_process_production_text,
)
from app.vtse.authoring.process_steps import extract_process_steps_from_rag


def test_filters_practice_and_placeholder_from_rag() -> None:
    rag = """
[Detailed — concept: digestion]

1. Food enters the mouth where chewing begins.
2. The stomach breaks food down with acids.

[Practice Question - For Reference Only]
Can non-living things grow?

3. Nutrients are absorbed in the intestines.
"""
    steps, stats = extract_process_steps_from_rag(rag, "digestion")
    labels = " ".join(s.label.lower() for s in steps)
    summaries = " ".join(s.summary.lower() for s in steps)
    assert "[practice question" not in labels
    assert "[practice question" not in summaries
    assert "[detailed" not in labels
    assert stats.filtered_practice_nodes >= 1
    assert stats.filtered_placeholder_count >= 1
    assert len(steps) >= 3


def test_scaffold_header_detection() -> None:
    assert is_authoring_scaffold_header("[Detailed — concept: living things]")
    assert is_practice_or_support_content("[Practice Question - For Reference Only]")


def test_sanitize_process_production_text() -> None:
    assert sanitize_process_production_text(
        "[Detailed — concept]",
        fallback="Step detail",
    ) == "Step detail"


def test_step_section_headers_merge_title_and_body() -> None:
    rag = """
Step 1 — Mouth
Digestion begins in the mouth. Teeth chew food into smaller pieces.

Step 2 — Esophagus
After swallowing, food moves through the esophagus.

Step 3 — Stomach
Acids and enzymes break food down further.
"""
    steps, _ = extract_process_steps_from_rag(rag, "digestion")
    labels = [s.label.lower() for s in steps]
    assert len(steps) == 3
    assert labels == ["mouth", "esophagus", "stomach"]
    assert "chew" in steps[0].summary.lower()
    assert "begins" not in steps[0].label.lower()


def test_coalesce_duplicate_mouth_fragments() -> None:
    rag = """
Digestion is the process of breaking food into nutrients the body can use.

Mouth
Digestion begins in the mouth. Teeth chew food.

Esophagus
Food moves through the esophagus after swallowing.

Stomach
The stomach uses acid to break food down.
"""
    steps, _ = extract_process_steps_from_rag(rag, "digestion")
    labels = [s.label.lower() for s in steps]
    assert len(steps) >= 3
    assert labels.count("mouth") == 1
    assert "mouth" in labels[0]
    assert all("stage 1" not in label for label in labels)
