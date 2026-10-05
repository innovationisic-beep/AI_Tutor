"""Tests for Zone 1 concept question orchestrator."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.constants import CONCEPT_QUESTIONS_PER_CONCEPT
from app.services.handlers.concept_question_orchestrator import (
    _cap_sentences,
    _followup_buttons,
    _keyword_overlap_correct,
    _partial_answer_correct,
    _short_correct_feedback,
    is_concept_questions_mode,
    normalize_concept_question_action,
)
from app.services.handlers.concept_taught_context import question_expects_single_item


def test_is_concept_questions_mode() -> None:
    assert is_concept_questions_mode(SimpleNamespace(concept_questions_active=False)) is False
    assert is_concept_questions_mode(SimpleNamespace(concept_questions_active=True)) is True


def test_concept_questions_per_concept_is_three() -> None:
    assert CONCEPT_QUESTIONS_PER_CONCEPT == 3


def test_normalize_concept_question_action_maps_legacy_buttons() -> None:
    session = SimpleNamespace(concept_question_followup=True, concept_question_clarifying=False)
    assert normalize_concept_question_action(session, action="ask_question", student_text="") == "ask_another"
    assert normalize_concept_question_action(session, action="understand", student_text="") == "concept_q_next"
    assert normalize_concept_question_action(session, action="skip", student_text="") is None


def test_keyword_overlap_correct_for_living_things() -> None:
    ref = "Living things grow, breathe, and reproduce."
    student = "grow, breathe and reproduce"
    assert _keyword_overlap_correct(student, ref) is True


def test_question_expects_single_item() -> None:
    assert question_expects_single_item("Tell one characteristic of living things.") is True
    assert question_expects_single_item("What are 3 characteristics of living things?") is False


def test_partial_answer_correct_for_one_characteristic() -> None:
    ref = "They grow, breathe, and reproduce."
    q = "Tell one characteristic of living things."
    assert _partial_answer_correct("grow", ref, question=q) is True
    assert _partial_answer_correct("breathe", ref, question=q) is True
    assert _partial_answer_correct("rock", ref, question=q) is False
    assert _partial_answer_correct("grow breeds and reproduce", ref, question=q) is False


def test_partial_answer_rejects_contradiction() -> None:
    ref = "Plants are living things."
    q = "Is a plant a living thing?"
    student = "no a plant cannot be considered as a living thing"
    assert _partial_answer_correct("living", ref, question=q) is False
    assert _keyword_overlap_correct(student, ref, question=q) is False


def test_short_correct_feedback_for_single_item_question() -> None:
    msg = _short_correct_feedback(
        "grow",
        "They grow, breathe, and reproduce.",
        question="Tell one characteristic of living things.",
        taught_ctx={"steps": [], "taught_points": ["Living things grow over time"]},
    )
    assert "grow" in msg.lower()
    assert "answer key" not in msg.lower()


def test_short_correct_feedback_for_step_count() -> None:
    msg = _short_correct_feedback(
        "4",
        "Correct answer for THIS lesson: 4 steps.",
        question="How many steps are in this cycle?",
        taught_ctx={
            "step_count": 4,
            "steps": ["Magma cools", "Weathering", "Erosion", "Heat"],
        },
    )
    assert "4" in msg
    assert "magma" in msg.lower() or "weathering" in msg.lower()


def test_short_correct_feedback_for_process_step() -> None:
    msg = _short_correct_feedback(
        "When magma cools it becomes igneous rock",
        "Magma cools into igneous rock",
        question="What happens first in the rock cycle?",
        taught_ctx={
            "step_count": 4,
            "steps": ["Magma cools into igneous rock", "Weathering", "Erosion", "Heat"],
        },
    )
    assert "magma" in msg.lower()
    assert len(msg) > 60


def test_short_correct_feedback_for_full_list() -> None:
    msg = _short_correct_feedback(
        "grow breathe reproduce",
        "Living things grow, breathe, and reproduce.",
        question="What are 3 characteristics of living things?",
    )
    assert "grow" in msg.lower()
    assert len(msg) > 50


def test_cap_sentences() -> None:
    text = "One. Two. Three. Four. Five."
    assert _cap_sentences(text, 2) == "One. Two."


def test_followup_buttons_last_question_label() -> None:
    mid = SimpleNamespace(concept_question_index=1)
    mid_labels = [b["label"] for b in _followup_buttons(mid)]
    assert "I understand — next question" in mid_labels

    last = SimpleNamespace(concept_question_index=2)
    last_labels = [b["label"] for b in _followup_buttons(last)]
    assert "I understand" in last_labels
    assert "I understand — next question" not in last_labels


def test_fallback_concept_notes_markdown() -> None:
    from app.services.handlers.concept_question_orchestrator import (
        _fallback_concept_notes_markdown,
    )

    md = _fallback_concept_notes_markdown(
        "Living things",
        {"taught_points": ["They grow", "They reproduce"], "steps": []},
        ['On "What is life?": answered "rocks"'],
    )
    assert "## Living things" in md
    assert "They grow" in md
    assert "Watch out" in md


def test_is_concept_notes_mode() -> None:
    from app.services.handlers.concept_question_orchestrator import (
        is_concept_notes_mode,
    )

    assert is_concept_notes_mode(SimpleNamespace(concept_notes_active=False)) is False
    assert is_concept_notes_mode(SimpleNamespace(concept_notes_active=True)) is True


@pytest.mark.asyncio
async def test_concept_check_board_rag_uses_taught_not_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Praise/wrong/clarify context must be board taught text, not VTSE template."""
    from app.services.handlers import concept_question_orchestrator as cq

    async def _fake_profile(*_a, **_k):
        return None

    async def _fake_topic(*_a, **_k):
        return SimpleNamespace(topic_name="Biology")

    monkeypatch.setattr(cq.StudentProfile, "find_one", _fake_profile)
    monkeypatch.setattr(cq, "_get_topic_or_teacher_topic_impl", _fake_topic)

    session = SimpleNamespace(
        organization_id=None,
        student_id=None,
        topic_id=None,
    )
    taught = {
        "teaching_facts": ["Living things grow over time."],
        "taught_points": ["Living things grow over time."],
        "steps": [],
        "lesson_excerpt": "Living things grow over time.",
    }
    ctx = SimpleNamespace(topic_repository=SimpleNamespace())
    _svc, context, _prof, _topic = await cq._concept_check_board_rag_bundle(
        ctx,  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        SimpleNamespace(topic_name="Biology"),  # type: ignore[arg-type]
        taught_ctx=taught,
    )
    assert "grow over time" in context.lower()
    assert "No authored VTSE template" not in context
