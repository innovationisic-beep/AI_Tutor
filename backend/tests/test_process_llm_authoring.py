"""LLM semantic process authoring — schema, resolver, and plan integration."""

from __future__ import annotations

from app.vtse.authoring.context import build_authoring_context
from app.vtse.authoring.plan_builder import build_teaching_plan
from app.vtse.authoring.process_authoring import resolve_linear_process_authoring
from app.vtse.authoring.process_step_schema import (
    ProcessLLMDraftV1,
    ProcessStepSemanticV1,
    trait_drafts_from_process_llm,
    validate_process_llm_draft,
)
from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft, TraitDraft


def _sample_llm_payload() -> dict:
    return {
        "topic": "Digestion Process",
        "semantic_process_confidence": 0.92,
        "narration_richness_level": "teacher_v1",
        "steps": [
            {
                "step_number": 1,
                "process_title": "Mouth",
                "concise_node_label": "Mouth",
                "explanation_text": "Digestion begins in the mouth where teeth chew food and saliva starts breakdown.",
                "narration_text": "First, food enters the mouth where chewing and saliva begin mechanical digestion.",
                "transition_reason": "",
                "pedagogical_role": "anchor",
            },
            {
                "step_number": 2,
                "process_title": "Stomach",
                "concise_node_label": "Stomach",
                "explanation_text": "The stomach uses acid and enzymes to break food into a semi-liquid mixture.",
                "narration_text": "After swallowing, the stomach continues digestion with acids and enzymes.",
                "transition_reason": "Once food is swallowed, it moves to the stomach for chemical breakdown.",
                "pedagogical_role": "explain",
            },
            {
                "step_number": 3,
                "process_title": "Intestines",
                "concise_node_label": "Intestines",
                "explanation_text": "Nutrients are absorbed in the small intestine as digestion completes.",
                "narration_text": "Finally, the intestines absorb nutrients the body needs.",
                "transition_reason": "After the stomach, partially digested food enters the intestines.",
                "pedagogical_role": "close",
            },
        ],
    }


def test_validate_process_llm_draft_accepts_teacher_schema() -> None:
    draft, dbg = validate_process_llm_draft(_sample_llm_payload())
    assert draft is not None
    assert dbg.get("valid_steps_after_validation") == 3
    assert draft.topic == "Digestion Process"
    assert len(draft.steps) == 3
    assert draft.steps[0].concise_node_label == "Mouth"
    assert draft.semantic_process_confidence == 0.92


def test_validate_process_llm_draft_rejects_too_few_steps() -> None:
    payload = _sample_llm_payload()
    payload["steps"] = payload["steps"][:2]
    draft, dbg = validate_process_llm_draft(payload)
    assert draft is None
    assert dbg.get("validation_failure_reason") == "insufficient_valid_steps"


def test_trait_drafts_from_process_llm_maps_renderer_fields() -> None:
    draft, _ = validate_process_llm_draft(_sample_llm_payload())
    assert draft is not None
    traits = trait_drafts_from_process_llm(draft)
    assert len(traits) == 3
    assert traits[0].label == "Mouth"
    assert "chew" in traits[0].summary.lower()
    assert "mouth" in traits[0].narration.lower()
    assert traits[0].kind == "process"


def _empty_draft() -> AuthoringSemanticDraft:
    return AuthoringSemanticDraft(
        topic_label="Digestion",
        concept_label="digestion",
        anchor_label="Digestion",
        anchor_summary="Digestion overview.",
        anchor_narration="We will walk through digestion.",
        traits=(),
        source="test",
    )


def test_resolve_linear_process_authoring_prefers_llm() -> None:
    draft = _empty_draft()
    llm, _ = validate_process_llm_draft(_sample_llm_payload())
    steps, stats, meta, source = resolve_linear_process_authoring(
        draft=draft,
        rag_context="Step 1 — Mouth\nOld rag text.",
        concept="digestion",
        process_llm_draft=llm,
    )
    assert source == "vtse_linear_process_llm_v1"
    assert meta.process_authoring_mode == "llm"
    assert meta.renderer_contract_valid is True
    assert meta.fallback_trigger_reason is None
    assert len(steps) == 3
    assert stats.process_step_count == 3


def test_resolve_linear_process_authoring_falls_back_to_rag() -> None:
    rag = """
Step 1 — Mouth
Digestion begins in the mouth.

Step 2 — Stomach
Acids break food down.

Step 3 — Intestines
Nutrients are absorbed.
"""
    draft = _empty_draft()
    steps, _stats, meta, source = resolve_linear_process_authoring(
        draft=draft,
        rag_context=rag,
        concept="digestion",
        process_llm_draft=None,
    )
    assert source == "vtse_linear_process_storyboard_v1"
    assert meta.process_authoring_mode == "deterministic"
    assert meta.fallback_trigger_reason is None
    assert len(steps) >= 3


def test_resolve_linear_process_authoring_reports_validation_fallback() -> None:
    draft = _empty_draft()
    invalid = ProcessLLMDraftV1(
        topic="Digestion",
        steps=(
            ProcessStepSemanticV1(
                step_number=1,
                process_title="Only",
                concise_node_label="Only",
                explanation_text="Single step is not enough for storyboard contract.",
                narration_text="Only one step here.",
            ),
        ),
        semantic_process_confidence=0.5,
        narration_richness_level="teacher_v1",
    )
    _steps, _stats, meta, source = resolve_linear_process_authoring(
        draft=draft,
        rag_context="",
        concept="digestion",
        process_llm_draft=invalid,
    )
    assert source == "vtse_linear_process_storyboard_v1"
    assert meta.process_authoring_mode == "deterministic"
    assert meta.fallback_trigger_reason == "validation_insufficient_steps"


def test_plan_builder_stamps_process_authoring_metadata() -> None:
    rag = """
Digestion process overview.

Step 1 — Mouth
Chewing begins digestion.

Step 2 — Stomach
Acids break food down.

Step 3 — Intestines
Nutrients are absorbed.
"""
    llm, _ = validate_process_llm_draft(_sample_llm_payload())
    ctx = build_authoring_context(
        topic_name="Digestion Process",
        concept="digestion",
        rag_context=rag,
        process_llm_draft=llm,
    )
    plan, selection = build_teaching_plan(
        ctx,
        session_id="s1",
        topic_id="t1",
        concept="digestion",
        forced_strategy_id="linear_process",
    )
    assert selection.semantic_shape == "linear_process"
    proc = plan.provenance.get("process_authoring") or {}
    assert proc.get("process_authoring_mode") == "llm"
    assert proc.get("renderer_contract_valid") is True
    assert plan.provenance.get("authoring_source") == "vtse_linear_process_llm_v1"
    assert len(plan.beats) == 3
    assert plan.semantic_graph.layout_hints.get("process_render_mode") == "process_storyboard_lanes"
