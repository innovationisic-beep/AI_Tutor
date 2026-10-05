"""DeepSeek Visual Teaching planner — semantic targets only, capability-gated."""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Sequence

import httpx

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.services.pedagogy.teacher_voice import (
    TEACHER_SPEAKING_CONTRACT,
    coarse_position_hint,
    continuity_instructions,
)
from app.services.curriculum.concept_vtse_context import (
    format_vtse_template_as_rag_context,
)
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    normalize_visual_teaching,
)
from app.services.visual_teaching.capabilities import SUPPORTED_VISUAL_CAPABILITIES
from app.services.visual_teaching.validate import (
    VisualTeachingPlanError,
    parse_plan_json,
    validate_plan_payload,
)
from app.services.visual_teaching.plan_schema import VisualTeachingPlan

logger = logging.getLogger(__name__)

MAX_OUTLINE_CHARS = 8000

_CAPS = ", ".join(sorted(SUPPORTED_VISUAL_CAPABILITIES))

_PLANNER_SYSTEM = f"""You are an expert school teacher planning a lesson that teaches FROM authored diagrams.

Return ONE JSON object only:
{{
  "capabilities_used": ["highlights","pointer",...],
  "scenes": [
    {{
      "asset_key": "...",
      "beats": [
        {{
          "id": "beat_1",
          "visual_state": {{
            "highlights": ["region_id"],
            "pointer": "region_id"|null,
            "labels_visible": ["region_id"],
            "dim_others": true|false,
            "zoom": {{"region_id": "..."}}|null,
            "arrows": ["connection_id"]
          }},
          "enter_effects": [],
          "speak": "spoken teacher text",
          "writes": [{{"source_sentence": "...", "text": "..."}}],
          "sentence_events": [
            {{"source_sentence": "...", "patch": {{"highlights": ["other_region"]}}}}
          ]
        }}
      ]
    }}
  ]
}}

HARD RULES
- Scenes MUST appear in the exact authored image order. One scene per authored asset_key. Do not omit or reorder.
- Reference ONLY supplied region_id / arrow_id (connection_id) / asset_key values. Never invent ids. Never emit coordinates.
- Regions are structures/areas to focus on. Arrows are authored direction/flow relationships with teaching_purpose explaining WHY they exist.
- visual_state is declarative COMPLETE overlay state at beat start. Compatible fields render TOGETHER on the same image — highlights, labels_visible, and arrows are NOT mutually exclusive.
- LABELS (default): When you highlight a region because it is being taught, ALSO include that same region_id in labels_visible so the student can read the label. Example: speak "This is the right atrium." → highlights:["right_atrium"] AND labels_visible:["right_atrium"]. Do not show every label on the image — only currently relevant taught regions. Highlight-without-label is allowed only when pedagogically intentional (rare).
- ARROWS: Each authored arrow has arrow_id, label, and teaching_purpose. When speech describes that directional relationship, include that arrow_id in visual_state.arrows. Example: speak "Blood returning from the body enters the right atrium." → highlights:["right_atrium"], labels_visible:["right_atrium"], arrows:["body_to_right_atrium"]. Choose arrows by teaching_purpose match — do not show an arrow merely because it exists; do not show every arrow at once.
- Prefer combinations like highlights + labels_visible + arrows when speech names a structure AND a direction/movement.
- sentence_events patches use field-replace semantics: omitted field preserves; [] or null clears. Omitting highlights while patching arrows keeps existing highlights and labels_visible.
- writes: only important ideas; source_sentence from speak; short board text — never full transcript.
- Orientation, attention, acknowledgement, and bridges stay in speak only. Never put them in writes.
- Each beat's speak names the highlighted region by its label, teaches from that region's teaching_purpose, and moves toward the next beat. Vary the opening. Do not start consecutive beats the same way.
- The last beat's speak moves toward continuity.next_focus when that field is present. That move is speech only and must not teach the next part's facts.
- Mention an arrow only when that arrow_id is included in visual_state.arrows.
- If a region includes position_hint, you may use that coarse placement. If position_hint is absent, refer only to the highlighted part. Never invent a placement.
- capabilities_used must be a subset of: {_CAPS}
- Do not use any capability outside that list.
- FACTUAL SOURCE OF TRUTH is AUTHORITATIVE_CONCEPT_OUTLINE. Image / region / arrow teaching_purpose values are pedagogical direction only.
- Warm, clear teacher speech. No markdown, no emoji, no stage directions.

""" + TEACHER_SPEAKING_CONTRACT


def _region_for_prompt(region: Any) -> dict:
    item = {
        "region_id": region.region_id,
        "label": region.label,
        "teaching_purpose": region.teaching_purpose,
    }
    hint = coarse_position_hint(
        shape=getattr(region, "shape", "") or "",
        geometry=getattr(region, "geometry", None),
        focus_point=getattr(region, "focus_point", None),
    )
    if hint:
        item["position_hint"] = hint
    return item


def _images_for_prompt(pkg: ConceptVisualTeaching) -> List[dict]:
    out: List[dict] = []
    for img in pkg.images:
        out.append(
            {
                "asset_key": img.asset_key,
                "teaching_purpose": img.teaching_purpose,
                "title": img.title,
                "regions": [_region_for_prompt(r) for r in img.regions],
                # Semantic arrows only — no coordinates. arrow_id == connection_id
                # used in visual_state.arrows.
                "arrows": [
                    {
                        "arrow_id": c.connection_id,
                        "label": c.label,
                        "teaching_purpose": c.teaching_purpose,
                    }
                    for c in img.connections
                ],
            }
        )
    return out


def build_visual_teaching_user_payload(
    *,
    pkg: ConceptVisualTeaching,
    vtse_template: Any,
    language: str = "en",
    concept_name: str = "",
    continuity: Optional[dict] = None,
) -> dict:
    outline = format_vtse_template_as_rag_context(vtse_template) or ""
    if len(outline) > MAX_OUTLINE_CHARS:
        outline = outline[:MAX_OUTLINE_CHARS]
    payload: dict = {
        "concept_name": concept_name,
        "language": language,
        "supported_capabilities": sorted(SUPPORTED_VISUAL_CAPABILITIES),
        "AUTHORITATIVE_CONCEPT_OUTLINE": outline,
        "teaching_images": _images_for_prompt(pkg),
    }
    if continuity:
        payload["continuity"] = {
            "previous_focus": str(continuity.get("previous_focus") or ""),
            "next_focus": str(continuity.get("next_focus") or ""),
            "student_thread": str(continuity.get("student_thread") or ""),
            "position_in_lesson": str(continuity.get("position_in_lesson") or ""),
        }
        note = continuity_instructions(continuity)
        if note:
            payload["continuity_instructions"] = note
    return payload


async def plan_visual_teaching(
    *,
    authored: ConceptVisualTeaching | dict,
    vtse_template: Any,
    language: str = "en",
    concept_name: str = "",
    settings: Optional[Settings] = None,
    continuity: Optional[dict] = None,
) -> VisualTeachingPlan:
    """
    Attempt DeepSeek plan → validate. Caller handles retry + skip-on-failure.
    Raises VisualTeachingPlanError on invalid output.
    """
    pkg = normalize_visual_teaching(authored)
    if pkg is None:
        raise VisualTeachingPlanError("empty authored package")

    cfg = settings or Settings()
    user_payload = build_visual_teaching_user_payload(
        pkg=pkg,
        vtse_template=vtse_template,
        language=language,
        concept_name=concept_name,
        continuity=continuity,
    )
    raw_text = await _call_deepseek(
        system=_PLANNER_SYSTEM,
        user=json.dumps(user_payload, ensure_ascii=False),
        cfg=cfg,
    )
    data = parse_plan_json(raw_text)
    return validate_plan_payload(
        data, authored=pkg, language=language, source="planner"
    )


async def plan_visual_teaching_with_retry(
    *,
    authored: ConceptVisualTeaching | dict,
    vtse_template: Any,
    language: str = "en",
    concept_name: str = "",
    settings: Optional[Settings] = None,
    continuity: Optional[dict] = None,
) -> Optional[VisualTeachingPlan]:
    """Attempt + one bounded retry. Returns None on failure (skip stage)."""
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            return await plan_visual_teaching(
                authored=authored,
                vtse_template=vtse_template,
                language=language,
                concept_name=concept_name,
                settings=settings,
                continuity=continuity,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning(
                "[VISUAL_TEACHING_PLANNER] attempt=%s failed: %s",
                attempt + 1,
                exc,
            )
    logger.error(
        "[VISUAL_TEACHING_PLANNER] giving_up concept=%s err=%s",
        concept_name,
        last_err,
    )
    return None


async def _call_deepseek(*, system: str, user: str, cfg: Settings) -> str:
    """
    DeepSeek chat completion — same endpoint/key pattern as Story Hook planner.
    """
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY") or getattr(cfg, "DEEPSEEK_API_KEY", None) or ""
    if not api_key:
        raise VisualTeachingPlanError("DEEPSEEK_API_KEY not configured")
    # Prefer full Settings.DEEPSEEK_API_URL (includes /v1/chat/completions).
    url = str(
        getattr(cfg, "DEEPSEEK_API_URL", None) or Settings.DEEPSEEK_API_URL or ""
    ).strip()
    if not url:
        raise VisualTeachingPlanError("DEEPSEEK_API_URL not configured")
    model = str(getattr(cfg, "DEEPSEEK_MODEL", None) or Settings.DEEPSEEK_MODEL or "deepseek-v4-pro")
    async with httpx.AsyncClient(timeout=90.0, http2=False) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.4,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "thinking": DEEPSEEK_THINKING_DISABLED,
            },
        )
        if resp.status_code != 200:
            raise VisualTeachingPlanError(
                f"DeepSeek HTTP {resp.status_code}: {(resp.text or '')[:240]}"
            )
        data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise VisualTeachingPlanError("malformed DeepSeek response") from exc
