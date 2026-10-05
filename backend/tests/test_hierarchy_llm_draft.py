"""Hierarchy semantic authoring — LLM draft schema, validator, question filter."""

from __future__ import annotations

import pytest

from app.vtse.authoring.content_filters import (
    is_question_text,
    is_unsuitable_hierarchy_label,
)
from app.vtse.authoring.llm_plan_draft import (
    HIERARCHY_LLM_MIN_TRAITS,
    HierarchyLLMDraftV1,
    validate_hierarchy_llm_draft,
)


# ── content_filters question detection ──────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Can non living things grow?",
    "What are 3 characteristics of living things?",
    "Why do plants need sunlight?",
    "How does photosynthesis work?",
    "Is water a living thing?",
    "Are animals multicellular?",
    "Name three properties of living things.",
    "List the stages of the water cycle.",
    "Describe how cells divide.",
])
def test_question_text_detected(text: str) -> None:
    assert is_question_text(text), f"Expected question to be detected: {text!r}"
    assert is_unsuitable_hierarchy_label(text)


@pytest.mark.parametrize("text", [
    "Grow",
    "Breathe",
    "Reproduce",
    "Need Energy",
    "Respond to Environment",
    "Cell Division",
])
def test_valid_labels_not_flagged(text: str) -> None:
    assert not is_question_text(text), f"Valid label flagged as question: {text!r}"
    assert not is_unsuitable_hierarchy_label(text)


# ── validate_hierarchy_llm_draft ────────────────────────────────────────────

def _good_payload(traits: list[dict] | None = None) -> dict:
    return {
        "topic": "Living Things",
        "anchor_label": "Living Things",
        "hierarchy_semantic_confidence": 0.85,
        "traits": traits or [
            {
                "concise_node_label": "Grow",
                "explanation_text": "Living things increase in size over time through cell division.",
                "narration_text": "One key sign of life is the ability to grow and develop.",
            },
            {
                "concise_node_label": "Breathe",
                "explanation_text": "Living things exchange gases such as oxygen and carbon dioxide.",
                "narration_text": "Breathing allows organisms to access energy from their environment.",
            },
            {
                "concise_node_label": "Reproduce",
                "explanation_text": "Living things create offspring to continue their species.",
                "narration_text": "Reproduction ensures the survival of each species over time.",
            },
        ],
    }


def test_valid_hierarchy_draft_accepted() -> None:
    draft, debug = validate_hierarchy_llm_draft(_good_payload())
    assert draft is not None
    assert isinstance(draft, HierarchyLLMDraftV1)
    assert len(draft.traits) == 3
    assert draft.topic == "Living Things"
    assert draft.hierarchy_semantic_confidence == pytest.approx(0.85)
    assert debug.get("hierarchy_authoring_mode") == "llm"
    assert debug.get("hierarchy_llm_traits_generated") == 3


def test_concise_node_labels_preserved() -> None:
    draft, _ = validate_hierarchy_llm_draft(_good_payload())
    assert draft is not None
    labels = [t.concise_node_label for t in draft.traits]
    assert "Grow" in labels
    assert "Breathe" in labels
    assert "Reproduce" in labels


def test_question_labels_rejected() -> None:
    payload = _good_payload(
        traits=[
            {
                "concise_node_label": "Can non living things grow?",
                "explanation_text": "Non living things cannot grow because they lack cells.",
                "narration_text": "Unlike living things, rocks do not grow.",
            },
            {
                "concise_node_label": "What are characteristics of life?",
                "explanation_text": "Characteristics of life include growth and reproduction.",
                "narration_text": "Life is defined by several key properties.",
            },
            {
                "concise_node_label": "Grow",
                "explanation_text": "Living things increase in size through cell division.",
                "narration_text": "Growth is a fundamental property of all living things.",
            },
        ]
    )
    draft, debug = validate_hierarchy_llm_draft(payload)
    # 2 question labels rejected; only 1 valid → below minimum → draft None
    assert draft is None
    assert debug.get("question_label_rejected", 0) >= 2


def test_sentence_fragment_label_truncated() -> None:
    payload = _good_payload(
        traits=[
            {
                "concise_node_label": "Living things are things that grow and reproduce",
                "explanation_text": "Living things demonstrate growth over their lifespan.",
                "narration_text": "Growth is one of the most visible signs of life.",
            },
            {
                "concise_node_label": "Breathe",
                "explanation_text": "Living things exchange gases such as oxygen.",
                "narration_text": "Breathing is essential for releasing energy.",
            },
            {
                "concise_node_label": "Reproduce",
                "explanation_text": "Living things produce offspring.",
                "narration_text": "Reproduction continues the species.",
            },
        ]
    )
    draft, debug = validate_hierarchy_llm_draft(payload)
    assert draft is not None
    # First trait label should have been truncated to ≤4 words (sentence fragment recovery)
    first_label = draft.traits[0].concise_node_label
    assert len(first_label.split()) <= 4, f"Label not truncated: {first_label!r}"
    assert debug.get("sentence_fragment_rejected", 0) >= 1


def test_missing_traits_array_rejected() -> None:
    draft, debug = validate_hierarchy_llm_draft({"topic": "Living Things"})
    assert draft is None
    assert "missing_traits_array" in (debug.get("validation_failure_reason") or "")


def test_too_few_traits_rejected() -> None:
    payload = _good_payload(
        traits=[
            {
                "concise_node_label": "Grow",
                "explanation_text": "Living things increase in size.",
                "narration_text": "Growth is a sign of life.",
            },
            {
                "concise_node_label": "Breathe",
                "explanation_text": "Living things exchange gases.",
                "narration_text": "Breathing keeps organisms alive.",
            },
        ]
    )
    draft, debug = validate_hierarchy_llm_draft(payload)
    assert draft is None
    assert "too_few_traits" in (debug.get("validation_failure_reason") or "")


def test_empty_explanation_rejected() -> None:
    payload = _good_payload(
        traits=[
            {"concise_node_label": "Grow", "explanation_text": "", "narration_text": ""},
            {"concise_node_label": "Breathe", "explanation_text": "short", "narration_text": "ok"},
            {
                "concise_node_label": "Reproduce",
                "explanation_text": "Living things produce offspring.",
                "narration_text": "Reproduction sustains species.",
            },
        ]
    )
    draft, debug = validate_hierarchy_llm_draft(payload)
    # 2 invalid (empty / too short explanation) → only 1 valid → below minimum
    assert draft is None


def test_semantic_expansion_ratio_computed() -> None:
    rag = "grow.\nbreathe.\nreproduce."
    payload = _good_payload()
    _, debug = validate_hierarchy_llm_draft(payload, rag_context=rag)
    ratio = debug.get("hierarchy_semantic_expansion_ratio")
    assert isinstance(ratio, float)
    assert ratio > 1.0  # expansions are longer than raw notes
