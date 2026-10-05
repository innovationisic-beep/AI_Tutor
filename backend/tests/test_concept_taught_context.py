"""Tests for concept-question taught-context alignment."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.handlers.concept_taught_context import (
    answer_contradicts_lesson,
    build_taught_context,
    is_step_count_question,
    parse_numeric_tokens,
    question_asks_about_process_step,
    resolve_reference_for_question,
    taught_content_supports_answer,
)


def test_step_count_question_detected() -> None:
    assert is_step_count_question("How many steps are in this cycle?") is True
    assert is_step_count_question("What is the rock cycle?") is False


def test_build_taught_context_from_timeline() -> None:
    session = SimpleNamespace(
        zone1_timeline_cache={
            "representation_type": "cycle",
            "beats": [
                {
                    "index": 0,
                    "operations": [
                        {
                            "op_type": "add_entity",
                            "payload": {
                                "entity": {
                                    "label": "Magma cools",
                                    "kind": "process",
                                }
                            },
                        }
                    ],
                },
                {
                    "index": 1,
                    "operations": [
                        {
                            "op_type": "add_entity",
                            "payload": {
                                "entity": {
                                    "label": "Weathering",
                                    "kind": "process",
                                }
                            },
                        }
                    ],
                },
            ],
        },
        flow_checkpoint_step_labels=[],
        taught_points=[],
        last_answer="The rock cycle has four main steps.",
    )
    ctx = build_taught_context(session)
    assert ctx["step_count"] == 2
    assert "Magma cools" in ctx["steps"]


def test_four_steps_accepted_when_taught_four() -> None:
    ctx = {"step_count": 4, "steps": ["A", "B", "C", "D"], "taught_points": []}
    assert taught_content_supports_answer("How many steps are in this cycle?", "4", ctx) is True
    assert taught_content_supports_answer("How many steps are in this cycle?", "four", ctx) is True
    assert taught_content_supports_answer("How many steps are in this cycle?", "7", ctx) is False


def test_resolve_reference_prefers_taught_step_count() -> None:
    ctx = {"step_count": 4, "steps": ["Magma cools", "Weathering", "Erosion", "Heat"], "taught_points": []}
    ref = resolve_reference_for_question(
        "How many steps are in this cycle?",
        "The rock cycle has 5 to 7 steps.",
        ctx,
    )
    assert "4" in ref
    assert "5 to 7" not in ref.split("AUTHORITATIVE")[0]


def test_magma_step_answer_supported() -> None:
    ctx = {
        "step_count": 4,
        "steps": ["Magma cools into igneous rock", "Weathering", "Erosion", "Heat and pressure"],
        "taught_points": [],
    }
    student = "When magma cools it hardens into solid rock"
    assert taught_content_supports_answer("What happens first in the rock cycle?", student, ctx) is True


def test_characteristic_question_does_not_auto_pass_on_keywords() -> None:
    ctx = {
        "step_count": 3,
        "steps": ["Grow", "Move", "Reproduce"],
        "taught_points": ["Living things grow over time"],
    }
    q = "Tell one characteristic of living things."
    assert question_asks_about_process_step(q) is False
    assert (
        taught_content_supports_answer(q, "grow breeds and reproduce", ctx) is False
    )
    assert (
        taught_content_supports_answer(
            q, "no a plant cannot be considered as a living thing", ctx
        )
        is False
    )


def test_answer_contradicts_lesson_negation() -> None:
    q = "Is a plant a living thing?"
    ref = "Yes, plants are living things."
    student = "no a plant cannot be considered as a living thing"
    assert answer_contradicts_lesson(student, q, ref) is True
    assert answer_contradicts_lesson("grow", q, ref) is False


def test_parse_numeric_tokens() -> None:
    assert 4 in parse_numeric_tokens("four")
    assert 4 in parse_numeric_tokens("4 steps")
