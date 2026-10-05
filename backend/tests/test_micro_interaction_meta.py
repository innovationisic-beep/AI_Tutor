"""Tests for concept-question prompt normalization."""

from app.services.handlers.micro_interaction_meta import (
    extract_micro_interaction_prompt,
    fallback_concept_question,
    is_meaningful_concept_question,
    normalize_concept_question_text,
)


def test_extract_prefers_full_question_over_option_fragment() -> None:
    text = (
        "Living things grow and reproduce. "
        "Which of these is a living thing? "
        "a rock, a tree, or a spoon?"
    )
    assert extract_micro_interaction_prompt(text) == (
        "Which of these is a living thing: a rock, a tree, or a spoon?"
    )


def test_normalize_merges_stem_with_option_fragment() -> None:
    text = "Which of these is a living thing?\na rock, a tree, or a spoon?"
    assert normalize_concept_question_text(text) == (
        "Which of these is a living thing: a rock, a tree, or a spoon?"
    )


def test_option_fragment_alone_is_not_meaningful() -> None:
    assert is_meaningful_concept_question("a rock, a tree, or a spoon?") is False


def test_complete_single_line_question_is_meaningful() -> None:
    q = "Which of these is a living thing: a rock, a tree, or a spoon?"
    assert is_meaningful_concept_question(q) is True


def test_fallback_when_text_is_only_fragment() -> None:
    out = normalize_concept_question_text(
        "a rock, a tree, or a spoon?",
        concept="Living things",
        question_index=2,
    )
    assert out == fallback_concept_question("Living things", 2)
    assert "Living things" in out


def test_extract_micro_interaction_prompt_simple() -> None:
    text = (
        "Living things need food and water. They grow over time. "
        "Can something grow but still not be alive?"
    )
    assert extract_micro_interaction_prompt(text) == (
        "Can something grow but still not be alive?"
    )


def test_short_yes_no_question_is_kept_not_fallback() -> None:
    """Authored short stems must display as-is (cluster quiz Q1 regression)."""
    q = "Do humans laugh?"
    assert is_meaningful_concept_question(q) is True
    assert normalize_concept_question_text(q) == q
    assert extract_micro_interaction_prompt(q) == q
    assert "important thing" not in extract_micro_interaction_prompt(q).lower()


def test_short_option_fragment_still_rejected() -> None:
    assert is_meaningful_concept_question("a rock or a tree?") is False
    assert "important thing" in normalize_concept_question_text(
        "a rock or a tree?", concept="this key idea"
    ).lower()


def test_fill_in_blank_stem_is_kept_not_fallback() -> None:
    """Concept-check Q3 fill-in must display the blank stem, not the generic prompt."""
    q = "Humans are _____."
    assert is_meaningful_concept_question(q) is True
    assert normalize_concept_question_text(q) == q
    assert extract_micro_interaction_prompt(q) == q
    assert "important thing" not in extract_micro_interaction_prompt(q).lower()


def test_short_fill_in_with_question_mark_kept() -> None:
    q = "Humans are _____?"
    assert is_meaningful_concept_question(q) is True
    assert normalize_concept_question_text(q) == q
