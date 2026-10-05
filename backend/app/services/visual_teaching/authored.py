"""Authored Visual Teaching package normalization + geometry validation."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, List, Literal, Optional, Sequence, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field

from app.services.curriculum.concept_teaching_sequence import (
    dedupe_asset_key,
    normalize_asset_key,
)

MAX_VISUAL_TEACHING_IMAGES = 8
MAX_REGIONS_PER_IMAGE = 24
MAX_ANCHORS_PER_IMAGE = 32
MAX_CONNECTIONS_PER_IMAGE = 24

AnnotationsStatus = Literal["confirmed", "stale"]
RegionShape = Literal["point", "rect", "ellipse", "polygon"]
ConnectionKind = Literal["flow", "compare", "generic"]

_ID_RE = re.compile(r"[^a-z0-9_]+")


def _field(raw: Any, name: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def _norm_id(raw: Any, *, fallback: str) -> str:
    slug = _ID_RE.sub("_", str(raw or "").strip().lower()).strip("_")
    slug = re.sub(r"_{2,}", "_", slug)
    return (slug or fallback)[:64]


def _clamp01(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _point(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    if "x" not in raw or "y" not in raw:
        return None
    return {"x": _clamp01(raw.get("x")), "y": _clamp01(raw.get("y"))}


def validate_region_geometry(shape: str, geometry: Any) -> Tuple[bool, str]:
    if not isinstance(geometry, dict):
        return False, "geometry must be an object"
    if shape == "point":
        if "x" not in geometry or "y" not in geometry:
            return False, "point requires x,y"
        return True, ""
    if shape == "rect":
        for k in ("x", "y", "w", "h"):
            if k not in geometry:
                return False, "rect requires x,y,w,h"
        w = float(geometry.get("w") or 0)
        h = float(geometry.get("h") or 0)
        if w <= 0 or h <= 0:
            return False, "rect w/h must be > 0"
        return True, ""
    if shape == "ellipse":
        for k in ("cx", "cy", "rx", "ry"):
            if k not in geometry:
                return False, "ellipse requires cx,cy,rx,ry"
        if float(geometry.get("rx") or 0) <= 0 or float(geometry.get("ry") or 0) <= 0:
            return False, "ellipse rx/ry must be > 0"
        return True, ""
    if shape == "polygon":
        pts = geometry.get("points")
        if not isinstance(pts, list) or len(pts) < 3:
            return False, "polygon requires ≥3 points"
        for p in pts:
            if not isinstance(p, dict) or "x" not in p or "y" not in p:
                return False, "polygon points must be {x,y}"
        return True, ""
    return False, f"unknown shape {shape}"


def normalize_region_geometry(shape: str, geometry: Any) -> dict:
    g = dict(geometry or {}) if isinstance(geometry, dict) else {}
    if shape == "point":
        return {"x": _clamp01(g.get("x")), "y": _clamp01(g.get("y"))}
    if shape == "rect":
        return {
            "x": _clamp01(g.get("x")),
            "y": _clamp01(g.get("y")),
            "w": _clamp01(g.get("w"), 0.01),
            "h": _clamp01(g.get("h"), 0.01),
        }
    if shape == "ellipse":
        return {
            "cx": _clamp01(g.get("cx")),
            "cy": _clamp01(g.get("cy")),
            "rx": _clamp01(g.get("rx"), 0.01),
            "ry": _clamp01(g.get("ry"), 0.01),
        }
    pts = g.get("points") if isinstance(g.get("points"), list) else []
    return {
        "points": [
            {"x": _clamp01(p.get("x")), "y": _clamp01(p.get("y"))}
            for p in pts
            if isinstance(p, dict)
        ]
    }


class VisualTeachingRegion(BaseModel):
    region_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    sort_order: int = Field(default=0, ge=0, le=999)
    shape: RegionShape = "rect"
    geometry: dict = Field(default_factory=dict)
    focus_point: Optional[dict] = None
    # Normalized label chrome {x,y,w,h} for authoring drag/resize (optional).
    label_box: Optional[dict] = None
    highlight_color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None


_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _hex_color(raw: Any, *, fallback: Optional[str] = None) -> Optional[str]:
    if raw is None:
        return fallback
    s = str(raw).strip()
    if not s:
        return fallback
    if not _HEX_RE.match(s):
        return fallback
    if len(s) == 4:
        return f"#{s[1]*2}{s[2]*2}{s[3]*2}".lower()
    return s.lower()


def _label_box(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x"))
        y = float(raw.get("y"))
        w = float(raw.get("w"))
        h = float(raw.get("h"))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None
    w = max(0.04, min(1.0, w))
    h = max(0.03, min(0.25, h))
    x = max(0.0, min(1.0 - w, x))
    y = max(0.0, min(1.0 - h, y))
    return {"x": x, "y": y, "w": w, "h": h}


class VisualTeachingAnchor(BaseModel):
    anchor_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    point: dict = Field(default_factory=dict)


class VisualTeachingConnection(BaseModel):
    connection_id: str = Field(default="", max_length=64)
    from_anchor: str = Field(default="", max_length=64)
    to_anchor: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    # Internal compatibility field — not exposed in authoring UI. Default flow.
    kind: ConnectionKind = "flow"
    color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None
    label_box: Optional[dict] = None


class VisualTeachingImage(BaseModel):
    id: str = Field(default="", max_length=64)
    asset_key: str = Field(default="", max_length=64)
    storage_key: str = Field(default="", max_length=512)
    mime_type: str = Field(default="", max_length=100)
    sort_order: int = Field(default=0, ge=0, le=999)
    title: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    natural_width: int = Field(default=0, ge=0)
    natural_height: int = Field(default=0, ge=0)
    content_hash: str = Field(default="", max_length=128)
    annotations_status: AnnotationsStatus = "confirmed"
    regions: List[VisualTeachingRegion] = Field(default_factory=list)
    anchors: List[VisualTeachingAnchor] = Field(default_factory=list)
    connections: List[VisualTeachingConnection] = Field(default_factory=list)


class ConceptVisualTeaching(BaseModel):
    images: List[VisualTeachingImage] = Field(default_factory=list)


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_visual_teaching_regions(raw: Any) -> List[VisualTeachingRegion]:
    items = list(raw or [])
    out: List[VisualTeachingRegion] = []
    keys: List[str] = []
    for index, item in enumerate(items[:MAX_REGIONS_PER_IMAGE]):
        shape_raw = str(_field(item, "shape") or "rect").strip().lower()
        shape: RegionShape = (
            shape_raw
            if shape_raw in ("point", "rect", "ellipse", "polygon")
            else "rect"
        )  # type: ignore[assignment]
        region_id = dedupe_asset_key(
            _norm_id(_field(item, "region_id"), fallback=f"region_{index + 1}"),
            keys,
        )
        keys.append(region_id)
        geom_raw = _field(item, "geometry") or {}
        ok, _ = validate_region_geometry(shape, geom_raw)
        if not ok:
            continue
        fp = _point(_field(item, "focus_point"))
        lb = _label_box(_field(item, "label_box"))
        out.append(
            VisualTeachingRegion(
                region_id=region_id,
                label=str(_field(item, "label") or "").strip(),
                teaching_purpose=str(_field(item, "teaching_purpose") or "").strip(),
                sort_order=len(out),
                shape=shape,
                geometry=normalize_region_geometry(shape, geom_raw),
                focus_point=fp,
                label_box=lb,
                highlight_color=_hex_color(_field(item, "highlight_color")),
                label_bg_color=_hex_color(_field(item, "label_bg_color")),
                label_text_color=_hex_color(_field(item, "label_text_color")),
            )
        )
    return out


def normalize_visual_teaching_anchors(raw: Any) -> List[VisualTeachingAnchor]:
    items = list(raw or [])
    out: List[VisualTeachingAnchor] = []
    keys: List[str] = []
    for index, item in enumerate(items[:MAX_ANCHORS_PER_IMAGE]):
        pt = _point(_field(item, "point"))
        if pt is None:
            continue
        aid = dedupe_asset_key(
            _norm_id(_field(item, "anchor_id"), fallback=f"anchor_{index + 1}"),
            keys,
        )
        keys.append(aid)
        out.append(
            VisualTeachingAnchor(
                anchor_id=aid,
                label=str(_field(item, "label") or "").strip(),
                point=pt,
            )
        )
    return out


def normalize_visual_teaching_connections(
    raw: Any, *, anchor_ids: Sequence[str]
) -> List[VisualTeachingConnection]:
    known = set(anchor_ids)
    items = list(raw or [])
    out: List[VisualTeachingConnection] = []
    keys: List[str] = []
    for index, item in enumerate(items[:MAX_CONNECTIONS_PER_IMAGE]):
        fr = str(_field(item, "from_anchor") or "").strip()
        to = str(_field(item, "to_anchor") or "").strip()
        if fr not in known or to not in known or fr == to:
            continue
        cid = dedupe_asset_key(
            _norm_id(
                _field(item, "connection_id"), fallback=f"connection_{index + 1}"
            ),
            keys,
        )
        keys.append(cid)
        # Authors do not choose kind; default flow for compatibility.
        kind_raw = str(_field(item, "kind") or "flow").strip().lower()
        kind: ConnectionKind = (
            kind_raw if kind_raw in ("flow", "compare", "generic") else "flow"
        )  # type: ignore[assignment]
        out.append(
            VisualTeachingConnection(
                connection_id=cid,
                from_anchor=fr,
                to_anchor=to,
                label=str(_field(item, "label") or "").strip(),
                teaching_purpose=str(
                    _field(item, "teaching_purpose") or ""
                ).strip(),
                kind=kind,
                color=_hex_color(_field(item, "color")),
                label_bg_color=_hex_color(_field(item, "label_bg_color")),
                label_text_color=_hex_color(_field(item, "label_text_color")),
                label_box=_label_box(_field(item, "label_box")),
            )
        )
    return out


def normalize_visual_teaching_images(raw: Any) -> List[VisualTeachingImage]:
    items = list(raw or [])
    out: List[VisualTeachingImage] = []
    keys: List[str] = []
    for index, item in enumerate(items[:MAX_VISUAL_TEACHING_IMAGES]):
        storage_key = str(_field(item, "storage_key") or "").strip()
        if not storage_key:
            continue
        key = dedupe_asset_key(
            normalize_asset_key(
                _field(item, "asset_key"), fallback=f"image_{index + 1}"
            ),
            keys,
        )
        keys.append(key)
        anchors = normalize_visual_teaching_anchors(_field(item, "anchors"))
        status_raw = str(_field(item, "annotations_status") or "confirmed").strip().lower()
        status: AnnotationsStatus = (
            "stale" if status_raw == "stale" else "confirmed"
        )
        out.append(
            VisualTeachingImage(
                id=str(_field(item, "id") or "").strip() or uuid4().hex,
                asset_key=key,
                storage_key=storage_key,
                mime_type=str(_field(item, "mime_type") or "").strip(),
                sort_order=len(out),
                title=str(_field(item, "title") or "").strip(),
                teaching_purpose=str(_field(item, "teaching_purpose") or "").strip(),
                natural_width=max(0, int(_field(item, "natural_width") or 0)),
                natural_height=max(0, int(_field(item, "natural_height") or 0)),
                content_hash=str(_field(item, "content_hash") or "").strip(),
                annotations_status=status,
                regions=normalize_visual_teaching_regions(_field(item, "regions")),
                anchors=anchors,
                connections=normalize_visual_teaching_connections(
                    _field(item, "connections"),
                    anchor_ids=[a.anchor_id for a in anchors],
                ),
            )
        )
    return out


def normalize_visual_teaching(raw: Any) -> Optional[ConceptVisualTeaching]:
    if raw is None:
        return None
    if isinstance(raw, ConceptVisualTeaching):
        return raw
    images_raw = raw.get("images") if isinstance(raw, dict) else getattr(raw, "images", None)
    images = normalize_visual_teaching_images(images_raw)
    if not images:
        return None
    return ConceptVisualTeaching(images=images)


def visual_teaching_has_content(raw: Any) -> bool:
    pkg = normalize_visual_teaching(raw)
    return bool(pkg and pkg.images)


def visual_teaching_storage_keys(raw: Any) -> set[str]:
    pkg = normalize_visual_teaching(raw)
    if not pkg:
        return set()
    return {img.storage_key for img in pkg.images if img.storage_key}


def mark_image_annotations_stale(image: VisualTeachingImage) -> VisualTeachingImage:
    """Any binary replace → annotations stale (dimensions/hash irrelevant)."""
    data = image.model_dump()
    data["annotations_status"] = "stale"
    return VisualTeachingImage.model_validate(data)


def apply_server_replace_stale(
    previous: Optional[ConceptVisualTeaching],
    incoming: ConceptVisualTeaching,
) -> ConceptVisualTeaching:
    """
    Server-authoritative replace→stale.

    If an image keeps the same asset_key (or id) but storage_key changes,
    force annotations_status=stale regardless of client payload.
    Confirmed is only allowed when storage_key is unchanged vs previous.
    """
    prev_by_key: dict[str, VisualTeachingImage] = {}
    prev_by_id: dict[str, VisualTeachingImage] = {}
    if previous:
        for img in previous.images:
            prev_by_key[img.asset_key] = img
            if img.id:
                prev_by_id[img.id] = img

    out: List[VisualTeachingImage] = []
    for img in incoming.images:
        prior = prev_by_id.get(img.id) if img.id else None
        if prior is None:
            prior = prev_by_key.get(img.asset_key)
        data = img.model_dump()
        if prior is not None and prior.storage_key and prior.storage_key != img.storage_key:
            data["annotations_status"] = "stale"
        elif prior is None:
            # Brand-new image: keep client status (usually confirmed after first annotate)
            pass
        else:
            # Same binary: allow confirmed only via explicit client reconfirm
            status = str(data.get("annotations_status") or "confirmed").strip().lower()
            data["annotations_status"] = "stale" if status == "stale" else "confirmed"
        out.append(VisualTeachingImage.model_validate(data))
    return ConceptVisualTeaching(images=out)


def _coord_in_unit(v: Any) -> bool:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return 0.0 <= x <= 1.0


def strict_geometry_errors(shape: str, geometry: Any) -> List[str]:
    """Publish-time geometry checks — no silent clamp acceptance of out-of-range."""
    errors: List[str] = []
    ok, msg = validate_region_geometry(shape, geometry)
    if not ok:
        return [msg or "invalid geometry"]
    g = geometry if isinstance(geometry, dict) else {}
    if shape == "point":
        if not _coord_in_unit(g.get("x")) or not _coord_in_unit(g.get("y")):
            errors.append("point coordinates must be in [0,1]")
    elif shape == "rect":
        for k in ("x", "y", "w", "h"):
            if not _coord_in_unit(g.get(k)):
                errors.append(f"rect.{k} must be in [0,1]")
        if float(g.get("w") or 0) <= 0 or float(g.get("h") or 0) <= 0:
            errors.append("rect w/h must be > 0")
    elif shape == "ellipse":
        for k in ("cx", "cy", "rx", "ry"):
            if not _coord_in_unit(g.get(k)):
                errors.append(f"ellipse.{k} must be in [0,1]")
    elif shape == "polygon":
        for i, p in enumerate(g.get("points") or []):
            if not isinstance(p, dict) or not _coord_in_unit(p.get("x")) or not _coord_in_unit(
                p.get("y")
            ):
                errors.append(f"polygon point {i} must be in [0,1]")
    return errors


def collect_raw_image_publish_errors(raw_img: Any) -> List[tuple[str, str]]:
    """
    Publish checks against authored payload before normalize can clamp/dedupe.
    """
    errors: List[tuple[str, str]] = []
    asset_key = str(_field(raw_img, "asset_key") or "image").strip() or "image"
    status = str(_field(raw_img, "annotations_status") or "confirmed").strip().lower()
    if status == "stale":
        errors.append(
            (
                "VISUAL_TEACHING_STALE_ANNOTATIONS",
                f'image "{asset_key}" annotations are stale — reconfirm before publish',
            )
        )

    region_ids: set[str] = set()
    for r in list(_field(raw_img, "regions") or []):
        rid = str(_field(r, "region_id") or "").strip()
        if rid and rid in region_ids:
            errors.append(
                (
                    "VISUAL_TEACHING_DUPLICATE_REGION_ID",
                    f'image "{asset_key}" duplicate region_id "{rid}"',
                )
            )
        if rid:
            region_ids.add(rid)
        shape = str(_field(r, "shape") or "rect").strip().lower()
        geom = _field(r, "geometry")
        for msg in strict_geometry_errors(shape, geom):
            errors.append(
                (
                    "VISUAL_TEACHING_INVALID_GEOMETRY",
                    f'image "{asset_key}" region "{rid or "?"}": {msg}',
                )
            )
        fp = _field(r, "focus_point")
        if fp is not None:
            if not isinstance(fp, dict) or not _coord_in_unit(fp.get("x")) or not _coord_in_unit(
                fp.get("y")
            ):
                errors.append(
                    (
                        "VISUAL_TEACHING_INVALID_FOCUS_POINT",
                        f'image "{asset_key}" region "{rid or "?"}" has invalid focus_point',
                    )
                )

    anchor_ids: set[str] = set()
    for a in list(_field(raw_img, "anchors") or []):
        aid = str(_field(a, "anchor_id") or "").strip()
        if aid and aid in anchor_ids:
            errors.append(
                (
                    "VISUAL_TEACHING_DUPLICATE_ANCHOR_ID",
                    f'image "{asset_key}" duplicate anchor_id "{aid}"',
                )
            )
        if aid:
            anchor_ids.add(aid)
        pt = _field(a, "point") or {}
        if not isinstance(pt, dict) or not _coord_in_unit(pt.get("x")) or not _coord_in_unit(
            pt.get("y")
        ):
            errors.append(
                (
                    "VISUAL_TEACHING_INVALID_ANCHOR",
                    f'image "{asset_key}" anchor "{aid or "?"}" has invalid coordinates',
                )
            )

    connection_ids: set[str] = set()
    for c in list(_field(raw_img, "connections") or []):
        cid = str(_field(c, "connection_id") or "").strip()
        fr = str(_field(c, "from_anchor") or "").strip()
        to = str(_field(c, "to_anchor") or "").strip()
        if cid and cid in connection_ids:
            errors.append(
                (
                    "VISUAL_TEACHING_DUPLICATE_CONNECTION_ID",
                    f'image "{asset_key}" duplicate connection_id "{cid}"',
                )
            )
        if cid:
            connection_ids.add(cid)
        if fr not in anchor_ids or to not in anchor_ids:
            errors.append(
                (
                    "VISUAL_TEACHING_INVALID_CONNECTION",
                    (
                        f'image "{asset_key}" connection "{cid or "?"}" '
                        "references unknown anchors"
                    ),
                )
            )
        if fr and to and fr == to:
            errors.append(
                (
                    "VISUAL_TEACHING_INVALID_CONNECTION",
                    f'image "{asset_key}" connection "{cid or "?"}" is self-referential',
                )
            )
    return errors
