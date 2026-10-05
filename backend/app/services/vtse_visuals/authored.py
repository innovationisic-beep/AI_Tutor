"""Optional VTSE image package. Reuses Visual Teaching region normalization."""

from __future__ import annotations

from typing import Any, Optional

from app.services.visual_teaching.authored import (
    apply_server_replace_stale,
    normalize_visual_teaching,
)

MAX_VTSE_IMAGES = 4
_SIDES = frozenset({"", "left", "right", "both"})


def _raw_images(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        images = raw.get("images") or []
    else:
        images = getattr(raw, "images", None) or []
    return list(images)[:MAX_VTSE_IMAGES]


def _bindings_for_region(item: Any) -> list[dict[str, Any]]:
    raw = item.get("bindings") if isinstance(item, dict) else getattr(item, "bindings", None)
    out: list[dict[str, Any]] = []
    for binding in list(raw or []):
        if not isinstance(binding, dict):
            continue
        key = str(binding.get("slot_key") or "").strip()
        if not key:
            continue
        side = str(binding.get("side") or "").strip().lower()
        if side not in _SIDES:
            side = ""
        try:
            index = int(binding.get("slot_index"))
        except (TypeError, ValueError):
            index = 0
        out.append(
            {
                "slot_kind": str(binding.get("slot_kind") or "").strip(),
                "slot_key": key,
                "slot_index": index,
                "side": side,
            }
        )
    return out


def normalize_vtse_visuals(raw: Any) -> Optional[dict[str, Any]]:
    """
    Normalize a VTSE visual package.

    ``None`` or an empty image list clears the field. Region geometry is the
    Visual Teaching normalizer. Bindings are reattached by region id.
    """
    images_raw = _raw_images(raw)
    if not images_raw:
        return None
    pkg = normalize_visual_teaching({"images": images_raw})
    if pkg is None or not pkg.images:
        return None
    bindings_by_region: dict[str, list[dict[str, Any]]] = {}
    for image in images_raw:
        regions = image.get("regions") if isinstance(image, dict) else None
        for region in list(regions or []):
            if not isinstance(region, dict):
                continue
            region_id = str(region.get("region_id") or "").strip()
            if not region_id:
                continue
            bindings_by_region[region_id] = _bindings_for_region(region)
    dumped = pkg.model_dump()
    for image in dumped.get("images") or []:
        for region in image.get("regions") or []:
            region_id = str(region.get("region_id") or "")
            region["bindings"] = list(bindings_by_region.get(region_id) or [])
    return dumped


def apply_vtse_visual_replace_stale(
    previous: Any,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Force stale annotations when the binary for an asset changes."""
    prev_pkg = normalize_visual_teaching(previous)
    next_pkg = normalize_visual_teaching(incoming)
    if next_pkg is None:
        return incoming
    stamped = apply_server_replace_stale(prev_pkg, next_pkg)
    status_by_key = {img.asset_key: img.annotations_status for img in stamped.images}
    out = dict(incoming)
    images = []
    for image in list(out.get("images") or []):
        data = dict(image)
        key = str(data.get("asset_key") or "")
        if key in status_by_key:
            data["annotations_status"] = status_by_key[key]
        images.append(data)
    out["images"] = images
    return out


def frozen_vtse_visuals(session: Any, live: Any) -> Any:
    """Prefer the lesson snapshot once this concept has been frozen."""
    frozen_idx = getattr(session, "concept_teaching_for_index", -1)
    current_idx = int(getattr(session, "current_concept_index", 0) or 0)
    if frozen_idx == current_idx and hasattr(
        session, "concept_teaching_vtse_visuals_snapshot"
    ):
        return getattr(session, "concept_teaching_vtse_visuals_snapshot", None)
    return live


def vtse_visual_storage_keys(raw: Any) -> set[str]:
    pkg = normalize_vtse_visuals(raw)
    if not pkg:
        return set()
    return {
        str(image.get("storage_key") or "")
        for image in pkg.get("images") or []
        if str(image.get("storage_key") or "")
    }


def public_vtse_visuals(raw: Any, *, concept_id: str) -> Optional[dict[str, Any]]:
    """Package safe to freeze on a timeline: no storage keys."""
    pkg = normalize_vtse_visuals(raw)
    if not pkg:
        return None
    images = []
    for image in pkg.get("images") or []:
        asset_key = str(image.get("asset_key") or "")
        images.append(
            {
                "asset_key": asset_key,
                "title": image.get("title") or "",
                "natural_width": image.get("natural_width") or 0,
                "natural_height": image.get("natural_height") or 0,
                "image_path": (
                    f"/curriculum/concepts/{concept_id}/vtse-visuals/images/{asset_key}"
                    if concept_id and asset_key
                    else ""
                ),
                "regions": list(image.get("regions") or []),
                "anchors": list(image.get("anchors") or []),
                "connections": list(image.get("connections") or []),
            }
        )
    return {"images": images}
