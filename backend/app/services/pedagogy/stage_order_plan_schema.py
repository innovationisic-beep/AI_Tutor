"""Structured output for Auto teaching-stage order. Order planning only."""

from __future__ import annotations

import json
import re
from typing import Any, List, Sequence

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_LIVE = frozenset({"story_hook", "visual_teaching", "vtse"})


class StageOrderPlanError(ValueError):
    """Model output that is not a permutation of the executable stages."""


def parse_stage_order_json(raw: str) -> dict[str, Any]:
    text = _JSON_FENCE_RE.sub("", raw or "").strip()
    if not text:
        raise StageOrderPlanError("empty")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise StageOrderPlanError("malformed_json") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            raise StageOrderPlanError("malformed_json") from None
    if not isinstance(parsed, dict):
        raise StageOrderPlanError("not_an_object")
    return parsed


def validate_stage_order_payload(
    payload: dict[str, Any],
    *,
    executable: Sequence[str],
) -> List[str]:
    """Accept only a permutation of ``executable``. Reason is ignored here."""
    expected = [str(s).strip().lower() for s in executable if str(s).strip()]
    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise StageOrderPlanError("empty_stages")
    stages = [str(s).strip().lower() for s in raw_stages if str(s).strip()]
    if len(stages) != len(raw_stages):
        raise StageOrderPlanError("blank_stage")
    if len(stages) != len(set(stages)):
        raise StageOrderPlanError("duplicate_stage")
    if any(stage not in _LIVE for stage in stages):
        raise StageOrderPlanError("unsupported_stage")
    if sorted(stages) != sorted(expected) or len(stages) != len(expected):
        raise StageOrderPlanError("stage_set_mismatch")
    return stages
