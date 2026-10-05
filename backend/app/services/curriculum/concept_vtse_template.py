"""Authored VTSE template helpers — lock strategy + payload per microconcept."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.vtse.authoring.process_step_schema import (
    ProcessLLMDraftV1,
    ProcessStepSemanticV1,
)
from app.vtse.registry.strategy_registry import STRATEGY_IDS

VtseStrategyId = Literal[
    "hierarchy_concept_intro",
    "clustered_trait_list",
    "comparison_contrast",
    "cycle_process",
    "linear_process",
]

ALLOWED_VTSE_STRATEGY_IDS: frozenset[str] = frozenset(STRATEGY_IDS)

STRATEGY_LABELS: Dict[str, str] = {
    "hierarchy_concept_intro": "Hierarchy",
    "clustered_trait_list": "Trait list",
    "comparison_contrast": "Comparison",
    "cycle_process": "Cycle",
    "linear_process": "Linear process",
}

_COMPARISON_MIN_ROWS = 2
_PROCESS_MIN_STEPS = 3
_TRAIT_MIN_STEPS = 3


class ConceptVtseTemplate(BaseModel):
    """Persisted authored VTSE template for a curriculum concept."""

    strategy_id: VtseStrategyId
    version: int = Field(default=1, ge=1)
    payload: Dict[str, Any] = Field(default_factory=dict)


def vtse_template_strategy_label(strategy_id: str | None) -> str:
    if not strategy_id:
        return ""
    return STRATEGY_LABELS.get(str(strategy_id), str(strategy_id))


def _http_400(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _clean_str(value: Any, *, max_len: int = 500) -> str:
    return str(value or "").strip()[:max_len]


def _normalize_comparison_payload(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise _http_400("INVALID_VTSE_PAYLOAD", "comparison payload must be an object")
    left_label = _clean_str(raw.get("left_label"), max_len=80)
    right_label = _clean_str(raw.get("right_label"), max_len=80)
    if not left_label or not right_label:
        raise _http_400(
            "INVALID_VTSE_PAYLOAD",
            "comparison requires left_label and right_label",
        )
    rows_in = raw.get("rows")
    if not isinstance(rows_in, list):
        raise _http_400("INVALID_VTSE_PAYLOAD", "comparison rows must be a list")
    rows: List[Dict[str, str]] = []
    for item in rows_in:
        if not isinstance(item, dict):
            continue
        dimension = _clean_str(item.get("dimension"), max_len=80) or "Compare"
        left = _clean_str(
            item.get("left")
            or item.get("left_detail")
            or item.get("left_summary")
            or item.get("left_title"),
            max_len=400,
        )
        right = _clean_str(
            item.get("right")
            or item.get("right_detail")
            or item.get("right_summary")
            or item.get("right_title"),
            max_len=400,
        )
        if not left and not right:
            continue
        rows.append(
            {
                "dimension": dimension,
                "left_detail": left,
                "right_detail": right,
                "left_title": _clean_str(item.get("left_title"), max_len=32) or dimension[:32],
                "right_title": _clean_str(item.get("right_title"), max_len=32) or dimension[:32],
            }
        )
    if len(rows) < _COMPARISON_MIN_ROWS:
        raise _http_400(
            "INVALID_VTSE_PAYLOAD",
            f"comparison requires at least {_COMPARISON_MIN_ROWS} point pairs",
        )
    return {
        "left_label": left_label,
        "right_label": right_label,
        "rows": rows,
    }


def _normalize_steps_payload(raw: Any, *, kind: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise _http_400("INVALID_VTSE_PAYLOAD", f"{kind} payload must be an object")
    steps_in = raw.get("steps") or raw.get("traits")
    if not isinstance(steps_in, list):
        raise _http_400("INVALID_VTSE_PAYLOAD", f"{kind} steps must be a list")
    steps: List[Dict[str, str]] = []
    for idx, item in enumerate(steps_in, start=1):
        if isinstance(item, str):
            label = _clean_str(item, max_len=120)
            summary = ""
            narration = ""
        elif isinstance(item, dict):
            label = _clean_str(
                item.get("label") or item.get("title") or item.get("concise_node_label"),
                max_len=120,
            )
            summary = _clean_str(
                item.get("summary")
                or item.get("annotation")
                or item.get("explanation_text")
                or item.get("detail"),
                max_len=600,
            )
            narration = _clean_str(
                item.get("narration") or item.get("narration_text"),
                max_len=600,
            )
        else:
            continue
        if not label and not summary:
            continue
        if not label:
            label = f"Step {idx}"
        if not summary:
            summary = label
        if not narration:
            narration = f"Next, {label}."
        steps.append({"label": label, "summary": summary, "narration": narration})
    min_n = _PROCESS_MIN_STEPS if kind in ("cycle", "linear") else _TRAIT_MIN_STEPS
    if len(steps) < min_n:
        raise _http_400(
            "INVALID_VTSE_PAYLOAD",
            f"{kind} requires at least {min_n} points",
        )
    return {"steps": steps}


def _normalize_payload_for_strategy(strategy_id: str, payload: Any) -> Dict[str, Any]:
    if strategy_id == "comparison_contrast":
        return _normalize_comparison_payload(payload)
    if strategy_id == "cycle_process":
        return _normalize_steps_payload(payload, kind="cycle")
    if strategy_id == "linear_process":
        return _normalize_steps_payload(payload, kind="linear")
    if strategy_id in ("clustered_trait_list", "hierarchy_concept_intro"):
        return _normalize_steps_payload(payload, kind="traits")
    raise _http_400("INVALID_VTSE_STRATEGY", f"Unsupported strategy_id '{strategy_id}'")


def normalize_vtse_template(raw: Any) -> Optional[ConceptVtseTemplate]:
    """
    Normalize authored template.

    ``None`` or empty clears the field.
    Invalid strategy/payload raises HTTP 400 (reject half-filled saves).
    """
    if raw is None:
        return None
    if isinstance(raw, ConceptVtseTemplate):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = dict(raw)
    elif hasattr(raw, "model_dump"):
        data = raw.model_dump()
    else:
        raise _http_400("INVALID_VTSE_TEMPLATE", "vtse_template must be an object or null")

    # Explicit clear: empty object or strategy_id ""
    strategy_raw = data.get("strategy_id")
    if strategy_raw is None or str(strategy_raw).strip() == "":
        payload = data.get("payload")
        if not payload:
            return None
        raise _http_400("INVALID_VTSE_STRATEGY", "strategy_id is required when payload is set")

    strategy_id = str(strategy_raw).strip()
    if strategy_id not in ALLOWED_VTSE_STRATEGY_IDS:
        raise _http_400(
            "INVALID_VTSE_STRATEGY",
            f"Invalid strategy_id '{strategy_id}'. Allowed: {', '.join(sorted(ALLOWED_VTSE_STRATEGY_IDS))}",
        )

    version = data.get("version", 1)
    try:
        version_i = int(version)
    except (TypeError, ValueError) as exc:
        raise _http_400("INVALID_VTSE_TEMPLATE", "version must be an integer") from exc
    if version_i < 1:
        raise _http_400("INVALID_VTSE_TEMPLATE", "version must be >= 1")

    payload = _normalize_payload_for_strategy(strategy_id, data.get("payload") or {})
    return ConceptVtseTemplate(
        strategy_id=strategy_id,  # type: ignore[arg-type]
        version=version_i,
        payload=payload,
    )


def vtse_template_to_dict(template: Optional[ConceptVtseTemplate]) -> Optional[Dict[str, Any]]:
    if template is None:
        return None
    return template.model_dump()


def force_shape_for_strategy(strategy_id: str) -> str:
    if strategy_id == "comparison_contrast":
        return "comparison"
    if strategy_id == "cycle_process":
        return "cycle"
    if strategy_id == "linear_process":
        return "linear_process"
    return "trait_list"


def materialize_vtse_template_inputs(
    template: ConceptVtseTemplate,
    *,
    topic_name: str,
    concept: str,
) -> Tuple[
    Optional[dict[str, Any]],
    Optional[ProcessLLMDraftV1],
    Optional[list[dict[str, Any]]],
    str,
]:
    """
    Convert authored template into Zone-1 authoring inputs.

    Returns (comparison_llm_json, process_llm_draft, trait_steps, forced_strategy_id).
    """
    strategy_id = template.strategy_id
    payload = template.payload or {}

    if strategy_id == "comparison_contrast":
        return (
            {
                "left_label": payload.get("left_label"),
                "right_label": payload.get("right_label"),
                "rows": list(payload.get("rows") or []),
            },
            None,
            None,
            strategy_id,
        )

    steps = list(payload.get("steps") or [])
    if strategy_id in ("cycle_process", "linear_process"):
        process_steps: list[ProcessStepSemanticV1] = []
        for idx, step in enumerate(steps, start=1):
            label = _clean_str(step.get("label"), max_len=80) or f"Step {idx}"
            summary = _clean_str(step.get("summary"), max_len=400) or label
            narration = _clean_str(step.get("narration"), max_len=400) or f"Next, {label}."
            process_steps.append(
                ProcessStepSemanticV1(
                    step_number=idx,
                    process_title=_clean_str(concept or topic_name, max_len=120) or "Process",
                    concise_node_label=label,
                    explanation_text=summary,
                    narration_text=narration,
                    pedagogical_role="explain",
                )
            )
        draft = ProcessLLMDraftV1(
            topic=_clean_str(concept or topic_name, max_len=120) or "Process",
            steps=tuple(process_steps),
            semantic_process_confidence=1.0,
            narration_richness_level="authored",
        )
        return None, draft, None, strategy_id

    trait_steps = [
        {
            "title": _clean_str(step.get("label"), max_len=120) or f"Point {i}",
            "annotation": _clean_str(step.get("summary"), max_len=400)
            or _clean_str(step.get("label"), max_len=120),
            "narration": _clean_str(step.get("narration"), max_len=400)
            or f"Next, {_clean_str(step.get('label'), max_len=80)}.",
        }
        for i, step in enumerate(steps, start=1)
        if isinstance(step, dict)
    ]
    return None, None, trait_steps, strategy_id
