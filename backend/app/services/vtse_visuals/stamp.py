"""Stamp optional image cues onto existing VTSE beats. Never adds beats."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.services.vtse_visuals.authored import public_vtse_visuals

logger = logging.getLogger(__name__)


def comparison_cue_boundary(
    narration: str,
    *,
    left_detail: str,
    right_detail: str,
) -> Optional[int]:
    """Character offset where the right-hand clause starts, or None."""
    text = narration or ""
    right = str(right_detail or "").strip().rstrip(".")
    left = str(left_detail or "").strip().rstrip(".")
    if right:
        idx = text.find(right)
        if idx > 0 and text.find(right, idx + 1) < 0:
            left_at = text.find(left) if left else -1
            if left_at < 0 or idx > left_at:
                return idx
    marker = "In contrast, "
    found = text.find(marker)
    if found > 0:
        return found
    return None


def _segment_text(beat: dict[str, Any]) -> str:
    segments = beat.get("narration_segments") or []
    if segments and isinstance(segments[0], dict):
        return str(segments[0].get("text") or "")
    return ""


def _regions_for_side(
    package: dict[str, Any],
    slot: dict[str, Any],
    side: str,
) -> list[tuple[str, str]]:
    """(asset_key, region_id) whose binding matches this slot and side."""
    found: list[tuple[str, str]] = []
    for image in package.get("images") or []:
        asset_key = str(image.get("asset_key") or "")
        for region in image.get("regions") or []:
            region_id = str(region.get("region_id") or "")
            if not asset_key or not region_id:
                continue
            for binding in region.get("bindings") or []:
                if not isinstance(binding, dict):
                    continue
                if str(binding.get("slot_key") or "") != str(slot.get("slot_key") or ""):
                    continue
                try:
                    if int(binding.get("slot_index")) != int(slot.get("slot_index")):
                        continue
                except (TypeError, ValueError):
                    continue
                bound_side = str(binding.get("side") or "")
                if side == "both":
                    if bound_side == "both":
                        found.append((asset_key, region_id))
                elif bound_side in (side, "both"):
                    found.append((asset_key, region_id))
    return found


def _cue(pairs: list[tuple[str, str]], *, char_start: int) -> Optional[dict[str, Any]]:
    if not pairs:
        return None
    return {
        "char_start": char_start,
        "asset_key": pairs[0][0],
        "region_ids": [region_id for _asset, region_id in pairs],
    }


def stamp_beat_visual(
    beat: dict[str, Any],
    slot: dict[str, Any],
    package: dict[str, Any],
    *,
    concept_id: str,
) -> None:
    owner = str(slot.get("narration_owner") or "")
    if owner == "comparison_row_suppressed" or slot.get("carry") is True:
        meta = beat.setdefault("metadata", {})
        if isinstance(meta, dict):
            meta["vtse_visual"] = {"carry": True}
        return

    side = str(slot.get("side") or "")
    kind = str(slot.get("slot_kind") or "")
    if kind == "row" and owner == "comparison_row_pair":
        left = _regions_for_side(package, slot, "left")
        right = _regions_for_side(package, slot, "right")
        narration = _segment_text(beat)
        boundary = comparison_cue_boundary(
            narration,
            left_detail=str(slot.get("left_detail") or ""),
            right_detail=str(slot.get("right_detail") or ""),
        )
        cues: list[dict[str, Any]] = []
        if boundary is not None and (left or right):
            first = _cue(left, char_start=0)
            second = _cue(right, char_start=boundary)
            if first:
                cues.append(first)
            if second:
                cues.append(second)
        if not cues:
            seen: set[str] = set()
            combined: list[tuple[str, str]] = []
            for pair in left + right:
                if pair[1] in seen:
                    continue
                seen.add(pair[1])
                combined.append(pair)
            whole = _cue(combined, char_start=0)
            if whole:
                cues.append(whole)
    else:
        pairs = _regions_for_side(package, slot, side or "left" if side else "")
        if not pairs and not side:
            pairs = []
            for image in package.get("images") or []:
                asset_key = str(image.get("asset_key") or "")
                for region in image.get("regions") or []:
                    region_id = str(region.get("region_id") or "")
                    for binding in region.get("bindings") or []:
                        if not isinstance(binding, dict):
                            continue
                        if str(binding.get("slot_key") or "") != str(slot.get("slot_key") or ""):
                            continue
                        try:
                            if int(binding.get("slot_index")) != int(slot.get("slot_index")):
                                continue
                        except (TypeError, ValueError):
                            continue
                        if asset_key and region_id:
                            pairs.append((asset_key, region_id))
        whole = _cue(pairs, char_start=0)
        cues = [whole] if whole else []

    if not cues:
        return
    asset_key = str(cues[0].get("asset_key") or "")
    meta = beat.setdefault("metadata", {})
    if not isinstance(meta, dict):
        return
    meta["vtse_visual"] = {
        "asset_key": asset_key,
        "region_ids": list(cues[-1].get("region_ids") or []),
        "image_path": (
            f"/curriculum/concepts/{concept_id}/vtse-visuals/images/{asset_key}"
            if concept_id and asset_key
            else ""
        ),
        "cues": cues,
    }


def attach_vtse_visuals(
    timeline: dict[str, Any],
    *,
    slots_by_beat: dict[str, Any],
    package: Optional[dict[str, Any]],
    concept_id: str,
) -> None:
    public = public_vtse_visuals(package, concept_id=concept_id)
    if not public or not public.get("images"):
        return
    meta = timeline.setdefault("metadata", {})
    if isinstance(meta, dict):
        meta["vtse_visual_package"] = public
    for beat in timeline.get("beats") or []:
        if not isinstance(beat, dict):
            continue
        slot = slots_by_beat.get(str(beat.get("beat_id") or ""))
        if not isinstance(slot, dict):
            continue
        stamp_beat_visual(beat, slot, public, concept_id=concept_id)


def safe_attach_vtse_visuals(
    timeline: dict[str, Any],
    *,
    slots_by_beat: dict[str, Any],
    package: Optional[dict[str, Any]],
    concept_id: str,
) -> None:
    try:
        attach_vtse_visuals(
            timeline,
            slots_by_beat=slots_by_beat,
            package=package,
            concept_id=concept_id,
        )
    except Exception:
        logger.exception("[VTSE_VISUAL] stamp_failed")
