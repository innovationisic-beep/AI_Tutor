"""Tests for cluster quiz question grounding."""

from app.services.handlers.cluster_check_question_service import (
    _cluster_pack_matches_taught,
    build_cluster_taught_context,
)
from app.services.handlers.concept_check_question_service import (
    _fallback_mcq_from_taught_context,
    is_quality_mcq_pack,
)
from app.services.handlers.concept_taught_context import (
    asked_quantity_in_question,
    question_count_matches_taught,
)


def test_asked_quantity_in_question() -> None:
    assert asked_quantity_in_question("What are the four steps on the board?") == 4
    assert asked_quantity_in_question("Name the three characteristics") == 3
    assert asked_quantity_in_question("Describe the four key points") == 4


def test_question_count_matches_taught_rejects_wrong_count() -> None:
    taught = {"step_count": 3, "taught_points": ["grow", "move", "reproduce"]}
    bad = "What are the four steps shown on the board that describe living things?"
    good = "What are the three characteristics shown on the board?"
    assert question_count_matches_taught(bad, taught) is False
    assert question_count_matches_taught(good, taught) is True


def test_cluster_pack_rejects_ungrounded_descriptive() -> None:
    taught = {
        "step_count": 3,
        "taught_points": ["They grow", "They move", "They reproduce"],
        "steps": ["They grow", "They move", "They reproduce"],
    }
    pack = {
        "question": "What are the four steps shown on the board?",
        "correct_answer": "grow, move, reproduce, breathe",
        "options": [],
        "type": "descriptive",
    }
    assert _cluster_pack_matches_taught(pack, taught, "descriptive") is False


def test_cluster_mcq_requires_grounded_correct_option() -> None:
    taught = {
        "step_count": 3,
        "taught_points": ["They grow", "They move", "They reproduce"],
        "steps": ["They grow", "They move", "They reproduce"],
    }
    bad = {
        "question": "Which statement about living things is correct?",
        "options": [
            "Living things never grow",
            "Living things need sunlight only",
            "All rocks are living",
            "Living things can reproduce",
        ],
        "correct_answer": "Living things can reproduce",
        "type": "mcq",
    }
    assert _cluster_pack_matches_taught(bad, taught, "mcq") is True

    ungrounded = {
        "question": "Which statement about living things is correct?",
        "options": [
            "Living things never grow",
            "Living things need sunlight only",
            "All rocks are living",
            "Living things photosynthesize always",
        ],
        "correct_answer": "Living things photosynthesize always",
        "type": "mcq",
    }
    assert _cluster_pack_matches_taught(ungrounded, taught, "mcq") is False

    ambiguous = {
        "question": "According to the lesson, which statement about Living things is correct?",
        "options": ["growth", "reproduction", "respiration", "living"],
        "correct_answer": "growth",
        "type": "mcq",
    }
    assert _cluster_pack_matches_taught(ambiguous, taught, "mcq") is False


def test_cluster_mcq_fallback_is_unambiguous() -> None:
    taught = {
        "step_count": 3,
        "taught_points": ["growth", "reproduction", "respiration"],
        "steps": ["growth", "reproduction", "respiration"],
    }
    pack = _fallback_mcq_from_taught_context("Living things", 0, taught)
    assert pack is not None
    assert is_quality_mcq_pack(pack, taught)
    assert pack["correct_answer"] == "3"
    assert all(len(o.split()) <= 2 or o.isdigit() for o in pack["options"])


def test_build_cluster_taught_context_uses_cluster_points() -> None:
    class S:
        cluster_taught_points = ["A", "B", "C"]
        taught_points = []
        zone1_timeline_cache = None
        flow_checkpoint_step_labels = []
        last_answer = None

    ctx = build_cluster_taught_context(S())  # type: ignore[arg-type]
    assert ctx["step_count"] == 3
    assert ctx["taught_points"] == ["A", "B", "C"]
