"""Concept teaching sequence helpers — Story Hook / VTSE / Visual Teaching."""

from __future__ import annotations

import re
from typing import Any, List, Literal, Optional, Sequence
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field

# ``media`` remains accepted for legacy authored docs but is never executed.
ConceptTeachingStage = Literal["vtse", "story_hook", "visual_teaching", "media"]

ALLOWED_TEACHING_STAGES: frozenset[str] = frozenset(
    {"vtse", "story_hook", "visual_teaching", "media"}
)
DEFAULT_TEACHING_SEQUENCE: List[ConceptTeachingStage] = ["vtse"]


MAX_STORY_HOOK_VISUALS = 6
_ASSET_KEY_RE = re.compile(r"[^a-z0-9_]+")


class ConceptStoryHookVisual(BaseModel):
    """
    A supporting Story Hook image.

    ``asset_key`` is the only identifier the planner LLM ever sees; ``storage_key``
    is opaque and owned by the storage provider.
    """

    id: str = Field(default="", max_length=64)
    asset_key: str = Field(default="", max_length=64)
    storage_key: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=600)
    teaching_purpose: str = Field(default="", max_length=600)
    mime_type: str = Field(default="", max_length=100)
    sort_order: int = Field(default=0, ge=0, le=999)


class ConceptStoryHook(BaseModel):
    """
    Author-authored narrative seed for a concept teaching stage.

    ``body`` is the Story Hook **seed** the planner builds from — not final
    narration. ``title``/``body`` are kept for backward compatibility.
    """

    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=8000)
    teacher_intent: str = Field(default="", max_length=2000)
    visuals: List[ConceptStoryHookVisual] = Field(default_factory=list)


def normalize_asset_key(raw: Any, *, fallback: str = "visual") -> str:
    """Slugify an author-supplied asset key: lowercase, ``a-z0-9_`` only."""
    slug = _ASSET_KEY_RE.sub("_", str(raw or "").strip().lower()).strip("_")
    slug = re.sub(r"_{2,}", "_", slug)
    return (slug or fallback)[:64]


def dedupe_asset_key(candidate: str, taken: Sequence[str]) -> str:
    """Return ``candidate`` or ``candidate-2``, ``-3``… when already used."""
    used = {str(k) for k in taken}
    if candidate not in used:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in used:
        suffix += 1
    return f"{candidate}-{suffix}"


def story_hook_has_content(hook: Any) -> bool:
    """
    True when the hook can drive the stage.

    Visuals alone are never enough — a Story Hook without a seed has nothing
    for the planner to ground on.
    """
    if hook is None:
        return False
    title = str(getattr(hook, "title", None) or (hook.get("title") if isinstance(hook, dict) else "") or "").strip()
    body = str(getattr(hook, "body", None) or (hook.get("body") if isinstance(hook, dict) else "") or "").strip()
    return bool(title or body)


def _visual_field(raw: Any, name: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def normalize_story_hook_visuals(raw: Any) -> List[ConceptStoryHookVisual]:
    """
    Normalize authored visuals: slugified unique ``asset_key``, stable ``id``,
    contiguous ``sort_order``. Entries without a ``storage_key`` are dropped
    because nothing could be rendered for them.
    """
    items = list(raw or [])
    out: List[ConceptStoryHookVisual] = []
    keys: List[str] = []
    for index, item in enumerate(items[:MAX_STORY_HOOK_VISUALS]):
        storage_key = str(_visual_field(item, "storage_key") or "").strip()
        if not storage_key:
            continue
        key = dedupe_asset_key(
            normalize_asset_key(
                _visual_field(item, "asset_key"), fallback=f"visual_{index + 1}"
            ),
            keys,
        )
        keys.append(key)
        out.append(
            ConceptStoryHookVisual(
                id=str(_visual_field(item, "id") or "").strip() or uuid4().hex,
                asset_key=key,
                storage_key=storage_key,
                description=str(_visual_field(item, "description") or "").strip(),
                teaching_purpose=str(
                    _visual_field(item, "teaching_purpose") or ""
                ).strip(),
                mime_type=str(_visual_field(item, "mime_type") or "").strip(),
                sort_order=len(out),
            )
        )
    return out


def normalize_story_hook(raw: Any) -> Optional[ConceptStoryHook]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        title = str(raw.get("title") or "").strip()
        body = str(raw.get("body") or "").strip()
        intent = str(raw.get("teacher_intent") or "").strip()
        visuals_raw = raw.get("visuals")
    else:
        title = str(getattr(raw, "title", "") or "").strip()
        body = str(getattr(raw, "body", "") or "").strip()
        intent = str(getattr(raw, "teacher_intent", "") or "").strip()
        visuals_raw = getattr(raw, "visuals", None)
    visuals = normalize_story_hook_visuals(visuals_raw)
    if not title and not body and not visuals:
        return None
    return ConceptStoryHook(
        title=title,
        body=body,
        teacher_intent=intent,
        visuals=visuals,
    )


def validate_teaching_sequence(raw: Optional[Sequence[str]]) -> List[ConceptTeachingStage]:
    """Validate author-configured sequence. Empty list means legacy default at runtime."""
    if raw is None:
        return []
    values = [str(v).strip().lower() for v in raw if str(v).strip()]
    if not values:
        return []
    seen: set[str] = set()
    out: List[ConceptTeachingStage] = []
    for stage in values:
        if stage not in ALLOWED_TEACHING_STAGES:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_TEACHING_STAGE",
                    "message": (
                        f"Invalid teaching_sequence stage '{stage}'. "
                        "Allowed: vtse, story_hook, visual_teaching, media"
                    ),
                },
            )
        if stage in seen:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DUPLICATE_TEACHING_STAGE",
                    "message": f"teaching_sequence contains duplicate stage '{stage}'",
                },
            )
        seen.add(stage)
        out.append(stage)  # type: ignore[arg-type]
    # Stages are independent: vtse, story_hook, and visual_teaching may appear
    # alone or in any order. No cross-stage ordering constraints.
    return out


def resolve_effective_teaching_sequence(
    *,
    teaching_sequence: Optional[Sequence[str]],
    story_hook: Any,
    visual_teaching: Any = None,
    media_available: bool = False,
) -> List[ConceptTeachingStage]:
    """
    Resolve runtime stages: start from authored sequence (or default VTSE),
    skip unavailable stages (empty story hook / visual teaching).

    Legacy ``media`` entries are ignored (replaced by Visual Teaching).
    """
    from app.services.visual_teaching.authored import visual_teaching_has_content

    configured = [str(v).strip().lower() for v in (teaching_sequence or []) if str(v).strip()]
    if not configured:
        configured = list(DEFAULT_TEACHING_SEQUENCE)

    effective: List[ConceptTeachingStage] = []
    for stage in configured:
        if stage not in ALLOWED_TEACHING_STAGES:
            continue
        if stage == "media":
            # Retired placeholder — Visual Teaching owns diagram teaching now.
            continue
        if stage == "story_hook" and not story_hook_has_content(story_hook):
            continue
        if stage == "visual_teaching" and not visual_teaching_has_content(visual_teaching):
            continue
        if stage == "vtse":
            effective.append("vtse")
        elif stage == "story_hook":
            effective.append("story_hook")
        elif stage == "visual_teaching":
            effective.append("visual_teaching")

    if not effective:
        return list(DEFAULT_TEACHING_SEQUENCE)
    return effective


_LIVE_STAGES = ("story_hook", "visual_teaching", "vtse")
_AUTO_REASON_MAX = 240


def normalize_teaching_sequence_mode(raw: Any) -> str:
    """Missing or blank is manual. Only manual and auto are valid."""
    mode = str(raw or "manual").strip().lower()
    if mode in ("", "manual"):
        return "manual"
    if mode == "auto":
        return "auto"
    raise HTTPException(
        status_code=400,
        detail={
            "code": "INVALID_TEACHING_SEQUENCE_MODE",
            "message": "teaching_sequence_mode must be manual or auto",
        },
    )


def _concept_value(concept: Any, name: str) -> Any:
    if concept is None:
        return None
    if isinstance(concept, dict):
        return concept.get(name)
    return getattr(concept, name, None)


def _usable_vtse_template(raw: Any) -> bool:
    from app.services.curriculum.concept_vtse_context import soft_normalize_vtse_template

    return soft_normalize_vtse_template(raw) is not None


def executable_stage_ids(concept: Any) -> List[str]:
    """
    Stages Auto may permute.

    Membership comes from the authored manual list (or the legacy VTSE default).
    A stage is executable only when it can run. The result is sorted so callers
    never treat manual arrow order as the Auto input order.
    """
    from app.services.visual_teaching.authored import visual_teaching_has_content

    raw = _concept_value(concept, "teaching_sequence")
    configured = [str(v).strip().lower() for v in (raw or []) if str(v).strip()]
    if not configured:
        configured = list(DEFAULT_TEACHING_SEQUENCE)
    story_hook = _concept_value(concept, "story_hook")
    visual = _concept_value(concept, "visual_teaching")
    template = _concept_value(concept, "vtse_template")
    found: set[str] = set()
    for stage in configured:
        if stage == "story_hook" and story_hook_has_content(story_hook):
            found.add("story_hook")
        elif stage == "visual_teaching" and visual_teaching_has_content(visual):
            found.add("visual_teaching")
        elif stage == "vtse" and _usable_vtse_template(template):
            found.add("vtse")
    return sorted(found)


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _bullet_list(raw: Any, *, limit: int = 6, each: int = 160) -> List[str]:
    items = list(raw or [])
    out: List[str] = []
    for item in items:
        text = _clip(item, each)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def teaching_sequence_auto_fingerprint(concept: Any) -> str:
    """Content stamp for the executable set. Manual arrow order is not included."""
    import hashlib
    import json

    stages = executable_stage_ids(concept)
    story_hook = _concept_value(concept, "story_hook") or {}
    visual = _concept_value(concept, "visual_teaching") or {}
    template = _concept_value(concept, "vtse_template") or {}
    images = []
    raw_images = visual.get("images") if isinstance(visual, dict) else getattr(visual, "images", None)
    for image in list(raw_images or []):
        if isinstance(image, dict):
            images.append(
                {
                    "asset_key": str(image.get("asset_key") or ""),
                    "purpose": _clip(image.get("teaching_purpose"), 160),
                }
            )
        else:
            images.append(
                {
                    "asset_key": str(getattr(image, "asset_key", "") or ""),
                    "purpose": _clip(getattr(image, "teaching_purpose", ""), 160),
                }
            )
    if isinstance(story_hook, dict):
        hook_stamp = {
            "title": str(story_hook.get("title") or ""),
            "body": str(story_hook.get("body") or ""),
            "intent": str(story_hook.get("teacher_intent") or ""),
        }
    else:
        hook_stamp = {
            "title": str(getattr(story_hook, "title", "") or ""),
            "body": str(getattr(story_hook, "body", "") or ""),
            "intent": str(getattr(story_hook, "teacher_intent", "") or ""),
        }
    if isinstance(template, dict):
        strategy = str(template.get("strategy_id") or "")
    else:
        strategy = str(getattr(template, "strategy_id", "") or "")
    payload = {
        "stages": stages,
        "study_points": _bullet_list(_concept_value(concept, "study_points")),
        "learning_outcomes": _bullet_list(_concept_value(concept, "learning_outcomes")),
        "story_hook": hook_stamp if "story_hook" in stages else None,
        "visual_teaching": images if "visual_teaching" in stages else None,
        "vtse": strategy if "vtse" in stages else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _auto_list_acceptable(
    auto: Sequence[str],
    executable: Sequence[str],
    manual_effective: Sequence[str],
) -> bool:
    cleaned = [str(s).strip().lower() for s in auto if str(s).strip()]
    if not cleaned or len(cleaned) != len(set(cleaned)):
        return False
    if any(stage not in _LIVE_STAGES for stage in cleaned):
        return False
    if executable:
        return sorted(cleaned) == list(executable)
    return cleaned == list(manual_effective)


def select_frozen_teaching_sequence(concept: Any) -> tuple[List[str], str]:
    """
    List to freeze, and source: manual | auto | auto_fallback.

    Does not call a model. Manual mode is exactly today's effective sequence.
    """
    manual = resolve_effective_teaching_sequence(
        teaching_sequence=_concept_value(concept, "teaching_sequence"),
        story_hook=_concept_value(concept, "story_hook"),
        visual_teaching=_concept_value(concept, "visual_teaching"),
        media_available=False,
    )
    mode = str(_concept_value(concept, "teaching_sequence_mode") or "manual").strip().lower()
    if concept is None or mode != "auto":
        return list(manual), "manual"
    auto = [
        str(s).strip().lower()
        for s in (_concept_value(concept, "teaching_sequence_auto") or [])
        if str(s).strip()
    ]
    status = str(_concept_value(concept, "teaching_sequence_auto_status") or "").strip().lower()
    stored_fp = str(_concept_value(concept, "teaching_sequence_auto_fingerprint") or "").strip()
    fingerprint = teaching_sequence_auto_fingerprint(concept)
    executable = executable_stage_ids(concept)
    if (
        status == "resolved"
        and stored_fp == fingerprint
        and _auto_list_acceptable(auto, executable, manual)
    ):
        return auto, "auto"
    return list(manual), "auto_fallback"


def auto_order_is_stale(concept: Any) -> bool:
    mode = str(_concept_value(concept, "teaching_sequence_mode") or "manual").strip().lower()
    if mode != "auto":
        return False
    status = str(_concept_value(concept, "teaching_sequence_auto_status") or "").strip().lower()
    if status != "resolved":
        return True
    stored = str(_concept_value(concept, "teaching_sequence_auto_fingerprint") or "").strip()
    return stored != teaching_sequence_auto_fingerprint(concept)


def clip_auto_reason(raw: Any) -> str:
    return _clip(raw, _AUTO_REASON_MAX) if str(raw or "").strip() else ""