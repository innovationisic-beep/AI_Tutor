"""
Choose a teaching-stage permutation. Does not rewrite stage content.

Called from author preview and publish only. Session freeze never calls this.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, List, Optional, Sequence

from app.services.curriculum.concept_teaching_sequence import (
    _bullet_list,
    _clip,
    _concept_value,
    clip_auto_reason,
    executable_stage_ids,
    resolve_effective_teaching_sequence,
    select_frozen_teaching_sequence,
    teaching_sequence_auto_fingerprint,
)
from app.services.pedagogy.stage_order_plan_schema import (
    StageOrderPlanError,
    parse_stage_order_json,
    validate_stage_order_payload,
)

logger = logging.getLogger(__name__)

LlmCall = Callable[..., Awaitable[Optional[str]]]

_SYSTEM = (
    "You choose only the order of teaching stages for one concept. "
    "Return JSON and nothing else: "
    '{"stages": ["story_hook", "visual_teaching", "vtse"], "reason": "one short sentence"}. '
    "stages must be a permutation of the available_stages set. "
    "Do not add, drop, or repeat a stage. "
    "Do not write lesson content, questions, or a lesson plan. "
    "available_stages is an unordered set shown in alphabetical order. "
    "That presentation is not a recommended order."
)


async def llm_call(user_content: str, *, system_content: str) -> Optional[str]:
    from app.services.story_hook.planner import llm_call as _deepseek

    return await _deepseek(
        user_content,
        system_content=system_content,
        temperature=0.2,
        timeout=20.0,
    )


def _hook_bits(concept: Any) -> dict[str, Any]:
    hook = _concept_value(concept, "story_hook") or {}
    if isinstance(hook, dict):
        title = hook.get("title")
        body = hook.get("body")
        intent = hook.get("teacher_intent")
        visuals = hook.get("visuals") or []
    else:
        title = getattr(hook, "title", "")
        body = getattr(hook, "body", "")
        intent = getattr(hook, "teacher_intent", "")
        visuals = getattr(hook, "visuals", None) or []
    return {
        "stage": "story_hook",
        "title": _clip(title, 120),
        "teacher_intent": _clip(intent, 200),
        "seed_excerpt": _clip(body, 200),
        "visual_count": len(list(visuals)),
    }


def _visual_bits(concept: Any) -> dict[str, Any]:
    visual = _concept_value(concept, "visual_teaching") or {}
    raw_images = (
        visual.get("images")
        if isinstance(visual, dict)
        else getattr(visual, "images", None)
    )
    cards: List[dict[str, str]] = []
    for image in list(raw_images or [])[:6]:
        if isinstance(image, dict):
            title = image.get("title")
            purpose = image.get("teaching_purpose")
        else:
            title = getattr(image, "title", "")
            purpose = getattr(image, "teaching_purpose", "")
        cards.append(
            {
                "title": _clip(title, 80),
                "teaching_purpose": _clip(purpose, 120),
            }
        )
    return {
        "stage": "visual_teaching",
        "image_count": len(list(raw_images or [])),
        "images": cards,
    }


def _vtse_bits(concept: Any) -> dict[str, Any]:
    from app.services.curriculum.concept_vtse_context import soft_normalize_vtse_template

    template = soft_normalize_vtse_template(_concept_value(concept, "vtse_template"))
    labels: List[str] = []
    strategy = ""
    if template is not None:
        strategy = str(template.strategy_id or "")
        payload = template.payload if isinstance(template.payload, dict) else {}
        labels = _short_labels(payload)
    return {
        "stage": "vtse",
        "strategy_id": strategy,
        "labels": labels[:8],
    }


def _short_labels(payload: Any, *, limit: int = 8) -> List[str]:
    found: List[str] = []

    def walk(node: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for key in ("title", "label", "name"):
                text = _clip(node.get(key), 80)
                if text and text not in found:
                    found.append(text)
                    if len(found) >= limit:
                        return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def build_stage_order_prompt(concept: Any, executable: Sequence[str]) -> str:
    """
    Canonical stage set plus authored concept context.

    The manual teaching_sequence order is intentionally absent.
    """
    stages = sorted(str(s).strip().lower() for s in executable if str(s).strip())
    cards = []
    if "story_hook" in stages:
        cards.append(_hook_bits(concept))
    if "visual_teaching" in stages:
        cards.append(_visual_bits(concept))
    if "vtse" in stages:
        cards.append(_vtse_bits(concept))
    cards.sort(key=lambda card: str(card.get("stage") or ""))
    body = {
        "concept_name": _clip(_concept_value(concept, "display_name"), 200),
        "study_points": _bullet_list(_concept_value(concept, "study_points")),
        "learning_outcomes": _bullet_list(_concept_value(concept, "learning_outcomes")),
        "available_stages": stages,
        "stage_cards": cards,
    }
    return json.dumps(body, ensure_ascii=False)


def _remember_fallback(concept: Any, manual: Sequence[str], fingerprint: str) -> str:
    concept.teaching_sequence_auto = list(manual)
    concept.teaching_sequence_auto_fingerprint = fingerprint
    concept.teaching_sequence_auto_reason = ""
    concept.teaching_sequence_auto_status = "fallback"
    return "fallback"


def _remember_resolved(
    concept: Any,
    stages: Sequence[str],
    *,
    fingerprint: str,
    reason: str,
) -> str:
    concept.teaching_sequence_auto = list(stages)
    concept.teaching_sequence_auto_fingerprint = fingerprint
    concept.teaching_sequence_auto_reason = clip_auto_reason(reason)
    concept.teaching_sequence_auto_status = "resolved"
    return "resolved"


async def resolve_auto_teaching_order(
    concept: Any,
    *,
    regenerate: bool = False,
    llm: Optional[LlmCall] = None,
) -> str:
    """
    Persist an Auto permutation or the manual effective sequence as fallback.

    Never writes ``teaching_sequence``. Returns ``resolved`` or ``fallback``.
    """
    manual = resolve_effective_teaching_sequence(
        teaching_sequence=_concept_value(concept, "teaching_sequence"),
        story_hook=_concept_value(concept, "story_hook"),
        visual_teaching=_concept_value(concept, "visual_teaching"),
        media_available=False,
    )
    executable = executable_stage_ids(concept)
    fingerprint = teaching_sequence_auto_fingerprint(concept)
    status = str(_concept_value(concept, "teaching_sequence_auto_status") or "").strip().lower()
    stored_fp = str(_concept_value(concept, "teaching_sequence_auto_fingerprint") or "").strip()
    if not regenerate and stored_fp == fingerprint and status == "fallback":
        return "fallback"
    if not regenerate and stored_fp == fingerprint and status == "resolved":
        _seq, source = select_frozen_teaching_sequence(concept)
        if source == "auto":
            return "resolved"
    if len(executable) < 2:
        chosen = list(executable) if executable else list(manual)
        return _remember_resolved(concept, chosen, fingerprint=fingerprint, reason="")

    caller = llm or llm_call
    prompt = build_stage_order_prompt(concept, executable)
    error = ""
    for _attempt in range(2):
        user = prompt if not error else prompt + f'\n\nprevious_error: {error}'
        try:
            raw = await caller(user, system_content=_SYSTEM)
        except Exception:  # noqa: BLE001
            logger.exception("[STAGE_ORDER] provider_error")
            return _remember_fallback(concept, manual, fingerprint)
        if not raw:
            error = "empty_provider_response"
            continue
        try:
            payload = parse_stage_order_json(raw)
            stages = validate_stage_order_payload(payload, executable=executable)
        except StageOrderPlanError as exc:
            error = str(exc)
            continue
        return _remember_resolved(
            concept,
            stages,
            fingerprint=fingerprint,
            reason=str(payload.get("reason") or ""),
        )
    logger.info("[STAGE_ORDER] fallback error=%s", error or "invalid")
    return _remember_fallback(concept, manual, fingerprint)
