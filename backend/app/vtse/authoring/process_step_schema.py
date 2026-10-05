"""Stable semantic contract between LLM process authoring and storyboard renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.cir.limits import CIR_V1_MAX_NODES
from app.vtse.authoring.comparison_rows import is_placeholder_text
from app.vtse.authoring.content_filters import (
    is_practice_or_support_content,
    sanitize_process_production_text,
)
from app.vtse.authoring.semantic_extract import TraitDraft, _clip

ProcessAuthoringMode = Literal["llm", "deterministic"]
PedagogicalRoleHint = Literal["anchor", "explain", "reinforce", "close", "transition"]

PROCESS_LLM_MIN_STEPS = 3
PROCESS_LLM_MAX_STEPS = CIR_V1_MAX_NODES

_VALID_ROLES = {"anchor", "explain", "reinforce", "close", "transition"}


@dataclass(frozen=True)
class ProcessStepSemanticV1:
    """One storyboard step — consumed by ``linear_process`` unchanged layout contract."""

    step_number: int
    process_title: str
    concise_node_label: str
    explanation_text: str
    narration_text: str
    transition_reason: str | None = None
    pedagogical_role: PedagogicalRoleHint | None = None


@dataclass(frozen=True)
class ProcessLLMDraftV1:
    """Validated LLM process lesson draft."""

    topic: str
    steps: tuple[ProcessStepSemanticV1, ...]
    semantic_process_confidence: float
    narration_richness_level: str


@dataclass(frozen=True)
class ProcessAuthoringMeta:
    """Observability for process semantic authoring."""

    process_authoring_mode: ProcessAuthoringMode
    llm_process_steps_generated: int | None = None
    semantic_process_confidence: float | None = None
    renderer_contract_valid: bool = True
    fallback_trigger_reason: str | None = None
    narration_richness_level: str | None = None
    authoring_source: str | None = None
    narration_generation_source: str | None = None
    deterministic_override_detected: bool | None = None
    semantic_expansion_ratio: float | None = None
    schema_clip_events: int | None = None
    debug: dict[str, Any] | None = None


def _clean_str(value: Any, *, max_len: int, fallback: str = "") -> str:
    text = sanitize_process_production_text(str(value or "").strip(), fallback=fallback, max_len=max_len)
    return _clip(text, max_len)


def _is_valid_explanation_text(text: str) -> bool:
    if not text or len(text) < 8:
        return False
    if is_placeholder_text(text) or is_practice_or_support_content(text):
        return False
    return True


def _is_valid_node_label(text: str) -> bool:
    if not text or len(text) < 2:
        return False
    if is_placeholder_text(text) or is_practice_or_support_content(text):
        return False
    return True


def _count_clip_events(raw: str, cleaned: str) -> int:
    if not raw or not cleaned:
        return 0
    return 1 if len(raw.strip()) > len(cleaned) + 8 else 0


def compute_semantic_expansion_ratio(
    draft: ProcessLLMDraftV1,
    *,
    rag_context: str | None,
) -> float:
    """Avg explanation length / avg RAG line length — higher means more synthesis."""
    rag_lines = [
        ln.strip()
        for ln in (rag_context or "").replace("\r", "").split("\n")
        if len(ln.strip()) >= 10
    ]
    rag_avg = sum(len(ln) for ln in rag_lines) / max(len(rag_lines), 1)
    expl_avg = sum(len(s.explanation_text) for s in draft.steps) / max(len(draft.steps), 1)
    return round(expl_avg / max(rag_avg, 1.0), 2)


def validate_process_llm_draft(
    payload: dict[str, Any] | None,
    *,
    rag_context: str | None = None,
) -> tuple[ProcessLLMDraftV1 | None, dict[str, Any]]:
    """
    Validate LLM JSON against renderer contract.

    Returns (draft or None, validation_debug).
    """
    debug: dict[str, Any] = {
        "validation_rejected_steps": 0,
        "schema_clip_events": 0,
    }
    if not payload or not isinstance(payload, dict):
        debug["validation_failure_reason"] = "empty_payload"
        return None, debug

    topic_raw = str(payload.get("topic") or payload.get("process_title") or "")
    topic = _clean_str(payload.get("topic") or payload.get("process_title"), max_len=120, fallback="Process")
    debug["schema_clip_events"] += _count_clip_events(topic_raw, topic)

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        debug["validation_failure_reason"] = "missing_steps_array"
        return None, debug

    steps: list[ProcessStepSemanticV1] = []
    for i, item in enumerate(raw_steps[:PROCESS_LLM_MAX_STEPS]):
        if not isinstance(item, dict):
            debug["validation_rejected_steps"] = int(debug["validation_rejected_steps"]) + 1
            continue
        step_number = int(item.get("step_number") or i + 1)
        title_raw = str(
            item.get("process_title") or item.get("title") or item.get("stage") or "",
        )
        process_title = _clean_str(
            item.get("process_title") or item.get("title") or item.get("stage"),
            max_len=80,
            fallback=f"Step {step_number}",
        )
        label_raw = str(
            item.get("concise_node_label") or item.get("node_label") or item.get("identity") or "",
        )
        node_label = _clean_str(
            item.get("concise_node_label") or item.get("node_label") or item.get("identity") or process_title,
            max_len=48,
            fallback=process_title,
        )
        expl_raw = str(
            item.get("explanation_text") or item.get("explanation") or item.get("summary") or "",
        )
        explanation = _clean_str(
            item.get("explanation_text") or item.get("explanation") or item.get("summary"),
            max_len=600,
            fallback="",
        )
        narr_raw = str(item.get("narration_text") or item.get("narration") or "")
        narration = _clean_str(
            item.get("narration_text") or item.get("narration"),
            max_len=400,
            fallback=explanation,
        )
        debug["schema_clip_events"] += (
            _count_clip_events(title_raw, process_title)
            + _count_clip_events(label_raw, node_label)
            + _count_clip_events(expl_raw, explanation)
            + _count_clip_events(narr_raw, narration)
        )
        if not _is_valid_node_label(node_label) or not _is_valid_explanation_text(explanation):
            debug["validation_rejected_steps"] = int(debug["validation_rejected_steps"]) + 1
            continue
        if len(node_label.split()) > 6:
            debug["validation_rejected_steps"] = int(debug["validation_rejected_steps"]) + 1
            continue

        transition = _clean_str(item.get("transition_reason") or "", max_len=200, fallback="")
        role_raw = str(item.get("pedagogical_role") or "").strip().lower()
        role: PedagogicalRoleHint | None = role_raw if role_raw in _VALID_ROLES else None

        steps.append(
            ProcessStepSemanticV1(
                step_number=step_number,
                process_title=process_title,
                concise_node_label=node_label,
                explanation_text=explanation,
                narration_text=narration or explanation,
                transition_reason=transition or None,
                pedagogical_role=role,
            ),
        )

    if len(steps) < PROCESS_LLM_MIN_STEPS:
        debug["validation_failure_reason"] = "insufficient_valid_steps"
        debug["valid_steps_after_validation"] = len(steps)
        return None, debug

    try:
        confidence = float(payload.get("semantic_process_confidence", 0.85))
    except (TypeError, ValueError):
        confidence = 0.85
    confidence = max(0.0, min(1.0, confidence))

    richness = _clean_str(payload.get("narration_richness_level") or "teacher_v1", max_len=32, fallback="teacher_v1")

    draft = ProcessLLMDraftV1(
        topic=topic,
        steps=tuple(steps),
        semantic_process_confidence=confidence,
        narration_richness_level=richness,
    )
    debug["valid_steps_after_validation"] = len(steps)
    if rag_context:
        debug["semantic_expansion_ratio"] = compute_semantic_expansion_ratio(
            draft,
            rag_context=rag_context,
        )
    return draft, debug


def process_authoring_meta_to_dict(meta: ProcessAuthoringMeta) -> dict[str, Any]:
    """Serialize observability for plan / timeline provenance."""
    out: dict[str, Any] = {
        "process_authoring_mode": meta.process_authoring_mode,
        "authoring_source": meta.authoring_source,
        "llm_process_steps_generated": meta.llm_process_steps_generated,
        "semantic_process_confidence": meta.semantic_process_confidence,
        "renderer_contract_valid": meta.renderer_contract_valid,
        "fallback_trigger_reason": meta.fallback_trigger_reason,
        "narration_richness_level": meta.narration_richness_level,
        "narration_generation_source": meta.narration_generation_source,
        "deterministic_override_detected": meta.deterministic_override_detected,
        "semantic_expansion_ratio": meta.semantic_expansion_ratio,
        "schema_clip_events": meta.schema_clip_events,
    }
    if meta.debug:
        out["process_llm_debug"] = meta.debug
    return out


def trait_drafts_from_process_llm(draft: ProcessLLMDraftV1) -> tuple[TraitDraft, ...]:
    """Map validated LLM draft → ``TraitDraft`` for ``build_linear_process_plan``."""
    out: list[TraitDraft] = []
    for step in draft.steps:
        narr = step.narration_text
        if step.transition_reason and step.transition_reason.lower() not in narr.lower():
            narr = _clip(f"{step.transition_reason} {narr}", 400)
        out.append(
            TraitDraft(
                label=_clip(step.concise_node_label, 80),
                summary=_clip(step.explanation_text, 600),
                narration=_clip(narr, 400),
                kind="process",
            ),
        )
    return tuple(out)
