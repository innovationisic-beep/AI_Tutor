"""Tests for structured concept-check question loading."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.constants import CONCEPT_CHECK_SLOT_TYPES
from app.services.handlers.concept_check_question_types import (
    infer_bank_question_type,
    mcq_answer_matches,
)
from app.services.handlers.concept_check_question_service import (
    _fallback_fill_in,
    _fallback_mcq,
    _validate_fill_in_payload,
    _validate_mcq_payload,
    apply_concept_check_pack_to_session,
    required_type_for_slot,
)


def test_slot_types_are_two_mcq_one_fill_in() -> None:
    assert CONCEPT_CHECK_SLOT_TYPES == ("mcq", "mcq", "fill_in_blank")
    assert required_type_for_slot(0) == "mcq"
    assert required_type_for_slot(1) == "mcq"
    assert required_type_for_slot(2) == "fill_in_blank"


def test_infer_bank_question_type_mcq() -> None:
    row = SimpleNamespace(
        question_type=None,
        question_text="What is X?",
        options=["A", "B", "C"],
        correct_answer="A",
    )
    assert infer_bank_question_type(row) == "mcq"


def test_infer_bank_question_type_fill_in() -> None:
    row = SimpleNamespace(
        question_type=None,
        question_text="Water freezes at _____ degrees.",
        options=[],
        correct_answer="0",
    )
    assert infer_bank_question_type(row) == "fill_in_blank"


def test_infer_bank_question_type_descriptive() -> None:
    row = SimpleNamespace(
        question_type=None,
        question_text="Explain photosynthesis in your own words.",
        options=[],
        correct_answer=None,
    )
    assert infer_bank_question_type(row) == "descriptive"


def test_validate_mcq_payload() -> None:
    pack = _validate_mcq_payload(
        {
            "question": "Which is a living thing?",
            "options": ["Rock", "Tree", "Sand", "Metal"],
            "correct_answer": "Tree",
            "explanation": "Trees grow.",
        }
    )
    assert pack is not None
    assert pack["type"] == "mcq"
    assert pack["correct_answer"] == "Tree"


def test_validate_mcq_payload_accepts_letter_key() -> None:
    pack = _validate_mcq_payload(
        {
            "question": "Where does digestion start?",
            "options": [
                "A) In the mouth",
                "B) In the lungs",
                "C) In the skin",
                "D) In the bones",
            ],
            "correct_answer": "B",
            "explanation": "Digestion begins in the mouth.",
        }
    )
    assert pack is not None
    assert pack["correct_answer"] == "In the lungs"


def test_fallback_mcq_from_taught_context_uses_lesson_steps() -> None:
    from app.services.handlers.concept_check_question_service import (
        _fallback_mcq_from_taught_context,
        is_quality_mcq_pack,
    )

    taught = {
        "steps": ["Mouth", "Stomach", "Small intestine"],
        "taught_points": [],
        "lesson_excerpt": "",
        "step_count": 3,
    }
    pack = _fallback_mcq_from_taught_context("Digestion Process", 0, taught)
    assert pack is not None
    assert pack["source"] == "taught_context"
    assert pack["correct_answer"] in pack["options"]
    assert is_quality_mcq_pack(pack, taught)
    assert "It is a key idea taught" not in " ".join(pack["options"])


def test_is_quality_mcq_pack_rejects_ambiguous_trait_options() -> None:
    from app.services.handlers.concept_check_question_service import (
        _fallback_mcq_from_taught_context,
        is_quality_mcq_pack,
    )

    taught = {
        "step_count": 3,
        "taught_points": ["growth", "reproduction", "respiration"],
        "steps": ["growth", "reproduction", "respiration"],
    }
    bad = {
        "question": "According to the lesson, which statement about Living things is correct?",
        "options": ["growth", "reproduction", "respiration", "living"],
        "correct_answer": "growth",
        "type": "mcq",
    }
    assert is_quality_mcq_pack(bad, taught) is False

    good = _fallback_mcq_from_taught_context("Living things", 0, taught)
    assert good is not None
    assert is_quality_mcq_pack(good, taught)
    assert good["correct_answer"] == "3"


def test_validate_fill_in_payload() -> None:
    pack = _validate_fill_in_payload(
        {
            "question": "Plants make food through _____.",
            "correct_answer": "photosynthesis",
            "explanation": "Core process.",
        }
    )
    assert pack is not None
    assert pack["type"] == "fill_in_blank"
    assert "_____" in pack["question"]


def test_validate_fill_in_rejects_weak_pronoun_blank() -> None:
    from app.services.handlers.concept_check_question_types import (
        is_strong_fill_in_answer,
        pick_fill_in_answer_from_fact,
    )

    assert is_strong_fill_in_answer("themselves") is False
    assert is_strong_fill_in_answer("things") is False
    assert is_strong_fill_in_answer("respire") is True
    assert is_strong_fill_in_answer("photosynthesis") is True

    weak = _validate_fill_in_payload(
        {
            "question": (
                "Because humans are living, they can move on their own "
                "and take care of _____?"
            ),
            "correct_answer": "themselves",
            "explanation": "Living humans care for themselves.",
        }
    )
    assert weak is None

    fact = (
        "Because humans are living, they can move on their own "
        "and take care of themselves."
    )
    picked = pick_fill_in_answer_from_fact(fact)
    assert picked is not None
    assert is_strong_fill_in_answer(picked)
    assert picked.lower() != "themselves"


def test_mcq_answer_matches() -> None:
    assert mcq_answer_matches("Tree", "Tree", ["Rock", "Tree"])
    assert not mcq_answer_matches("Rock", "Tree", ["Rock", "Tree"])
    opts = ["Growth", "Reproduction", "Made of plastic"]
    assert mcq_answer_matches("Growth", "Growth", opts)
    polluted = (
        "Growth\n\nAUTHORITATIVE — grade ONLY against what was taught in this lesson:\n"
        "Living things grow, reproduce, and respond."
    )
    assert mcq_answer_matches("Growth", polluted, opts)
    assert not mcq_answer_matches("Made of plastic", "Growth", opts)


@pytest.mark.asyncio
async def test_evaluate_mcq_uses_keyed_answer_not_lesson_block() -> None:
    from app.services.handlers.concept_question_orchestrator import (
        _evaluate_concept_answer,
    )

    polluted = (
        "Growth\n\nAUTHORITATIVE — grade ONLY against what was taught in this lesson:\n"
        "Living things grow, reproduce, and respond."
    )
    correct, score = await _evaluate_concept_answer(
        "living things",
        "Name one characteristic of living things.",
        "Growth",
        polluted,
        question_type="mcq",
        mcq_options=["Growth", "Reproduction", "They do not change"],
    )
    assert correct is True
    assert score >= 60

    correct, score = await _evaluate_concept_answer(
        "living things",
        "Name one characteristic of living things.",
        "Growth",
        "Growth",
        question_type="mcq",
        mcq_options=["Growth", "Reproduction", "They do not change"],
    )
    assert correct is True
    assert score >= 60


@pytest.mark.asyncio
async def test_evaluate_mcq_inferred_from_options_without_type() -> None:
    from app.services.handlers.concept_question_orchestrator import (
        _evaluate_concept_answer,
    )

    correct, _ = await _evaluate_concept_answer(
        "living things",
        "Which is living?",
        "Tree",
        "Tree",
        question_type=None,
        mcq_options=["Rock", "Tree", "Sand"],
    )
    assert correct is True


def test_pack_matches_taught_rejects_meta_llm_stems() -> None:
    from app.services.handlers.teaching_transcript_service import pack_matches_taught

    taught = {
        "teaching_facts": [
            "Living things grow over time and reproduce to make offspring.",
            "Plants breathe in carbon dioxide and release oxygen.",
        ],
        "step_count": 2,
    }
    assert not pack_matches_taught(
        {
            "question": "What is the main topic of today's lesson?",
            "options": ["Living things", "Rocks", "Water", "Air"],
            "correct_answer": "Living things",
            "type": "mcq",
        },
        taught,
        required_type="mcq",
    )
    assert not pack_matches_taught(
        {
            "question": (
                "What does the teacher mean when they say, "
                "'You've nailed the big idea right from the beginning'?"
            ),
            "options": ["Praise", "Correction", "Warning", "Question"],
            "correct_answer": "Praise",
            "type": "mcq",
        },
        taught,
        required_type="mcq",
    )


def test_apply_pack_to_session_mcq() -> None:
    session = SimpleNamespace(
        current_question=None,
        current_concept_question_answer=None,
        current_concept_question_type=None,
        current_concept_question_options=[],
        concept_question_index=0,
        concept_question_followup=True,
        concept_question_clarifying=True,
        concept_question_pending_advance=True,
    )
    pack = _fallback_mcq("living things", 0)
    apply_concept_check_pack_to_session(session, pack, 0)
    assert session.current_concept_question_type == "mcq"
    assert len(session.current_concept_question_options) >= 3
    assert session.concept_question_index == 0
    assert session.concept_question_followup is False


def test_apply_pack_to_session_fill_in() -> None:
    session = SimpleNamespace(
        current_question=None,
        current_concept_question_answer=None,
        current_concept_question_type=None,
        current_concept_question_options=[],
        concept_question_index=0,
        concept_question_followup=False,
        concept_question_clarifying=False,
        concept_question_pending_advance=False,
    )
    pack = _fallback_fill_in("photosynthesis")
    apply_concept_check_pack_to_session(session, pack, 2)
    assert session.current_concept_question_type == "fill_in_blank"
    assert session.current_concept_question_options == []
    assert session.concept_question_index == 2


@pytest.mark.asyncio
async def test_session_meta_includes_concept_question_type() -> None:
    from app.services.handlers.session_meta import build_teacher_session_meta

    session = SimpleNamespace(
        total_concepts=3,
        key_concepts=["a"],
        concept_clusters=None,
        current_concept_index=0,
        current_cluster_index=0,
        current_zone=1,
        explanation_mode="rag",
        concept_questions_active=True,
        concept_question_index=1,
        concept_question_followup=False,
        concept_question_clarifying=False,
        concept_question_pending_advance=False,
        current_question="Which is true?",
        current_concept_question_type="mcq",
        current_concept_question_options=["A", "B", "C"],
        flow_state="concept_questions",
        sus_score=50.0,
        zone2_depth="medium",
    )
    meta = build_teacher_session_meta(session, topic=None)
    assert meta is not None
    assert meta["concept_question_type"] == "mcq"
    assert meta["concept_question_options"] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_evaluate_mcq_in_orchestrator() -> None:
    from app.services.handlers.concept_question_orchestrator import (
        _evaluate_concept_answer,
    )

    correct, score = await _evaluate_concept_answer(
        "living things",
        "Which is living?",
        "Tree",
        "Tree",
        question_type="mcq",
        mcq_options=["Rock", "Tree", "Sand"],
    )
    assert correct is True
    assert score >= 60

    wrong, _ = await _evaluate_concept_answer(
        "living things",
        "Which is living?",
        "Rock",
        "Tree",
        question_type="mcq",
        mcq_options=["Rock", "Tree", "Sand"],
    )
    assert wrong is False
