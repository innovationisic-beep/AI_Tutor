"""Validation helpers for structured curriculum authoring."""

from __future__ import annotations

import re

from app.models.curriculum.curriculum_enums import CurriculumZonePurpose

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_slug(value: str) -> str:
    raw = (value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not slug:
        raise ValueError("slug cannot be empty")
    if len(slug) > 160:
        slug = slug[:160].rstrip("-")
    return slug


def validate_slug_format(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_RE.match(s):
        raise ValueError(
            "slug must be lowercase alphanumeric segments separated by hyphens"
        )
    return s


def purpose_for_zone_number(zone_number: int) -> CurriculumZonePurpose:
    mapping: dict[int, CurriculumZonePurpose] = {
        0: "curiosity",
        1: "core_teaching",
        2: "extension_1",
        3: "extension_2",
        4: "extension_3",
    }
    if zone_number not in mapping:
        raise ValueError("zone_number must be between 0 and 4")
    return mapping[zone_number]


def allows_vtse_for_zone(zone_number: int) -> bool:
    """Zones 1–2 use the VTSE whiteboard teaching engine."""
    return zone_number in (1, 2)


def is_system_zone_for_number(zone_number: int) -> bool:
    return zone_number == 0


def next_cluster_number(existing: list[int]) -> int:
    if not existing:
        return 1
    return max(existing) + 1


def normalize_runtime_key(value: str) -> str:
    """Stable runtime identity string (matches TopicNote.concept storage rules)."""
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("canonical_runtime_key cannot be empty")
    if len(raw) > 500:
        raw = raw[:500].rstrip()
    return raw


def assign_canonical_runtime_key(
    *,
    explicit: str | None,
    legacy_concept_key: str | None,
    display_name: str,
) -> str:
    if explicit and explicit.strip():
        return normalize_runtime_key(explicit)
    if legacy_concept_key and legacy_concept_key.strip():
        return normalize_runtime_key(legacy_concept_key)
    return normalize_runtime_key(display_name)
