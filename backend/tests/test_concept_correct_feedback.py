"""Tests for student-facing correct-answer praise messages."""

from __future__ import annotations

from app.services.handlers.concept_taught_context import (
    build_correct_answer_message,
    clean_db_answer_for_display,
    is_grading_boilerplate,
)


def test_clean_db_answer_strips_boilerplate() -> None:
    assert clean_db_answer_for_display("Use the lesson content below as the answer key.") == ""
    assert (
        clean_db_answer_for_display("Plants make glucose using sunlight.")
        == "Plants make glucose using sunlight."
    )


def test_photosynthesis_energy_explanation() -> None:
    msg = build_correct_answer_message(
        "energy",
        "What do plants make from photosynthesis?",
        "Glucose and food energy from sunlight.",
        {"steps": [], "taught_points": []},
        praise="That's right — nice work.",
    )
    assert "energy" in msg.lower()
    assert "photosynth" in msg.lower()
    assert "answer key" not in msg.lower()


def test_never_shows_grading_boilerplate() -> None:
    msg = build_correct_answer_message(
        "grow",
        "Tell one characteristic of living things.",
        "Use the lesson content below as the answer key.\n\nAUTHORITATIVE — grade ONLY",
        {"steps": [], "taught_points": ["Living things grow over time"]},
        praise="Exactly — you've got it.",
    )
    assert not is_grading_boilerplate(msg)
    assert "answer key" not in msg.lower()
    assert "grow" in msg.lower()
