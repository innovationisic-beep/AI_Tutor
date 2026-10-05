"""
One-time cleanup for Organization documents:

- Remove legacy root-level ``subjects`` (merge into ``classes[].subjects[]`` when non-empty).
- Deduplicate subjects **per class** by name (trim + case-insensitive): keep one row,
  preferring a subject with ``curriculum_subject_id`` set, else the first occurrence.

Run from repository backend directory::

    python -m scripts.cleanup_org_subjects
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections import defaultdict
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient


def _subject_name_key(name: Any) -> str:
    """Trim + lowercase for duplicate comparison."""
    return str(name or "").strip().lower()


def _has_curriculum_link(s: dict[str, Any]) -> bool:
    v = s.get("curriculum_subject_id")
    return v is not None and str(v).strip() != ""


def _pick_subject_to_keep(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer an entry with curriculum_subject_id; else first in list order."""
    for s in group:
        if _has_curriculum_link(s):
            return s
    return group[0]


def _dedupe_subjects_in_class(subs: list[Any]) -> tuple[list[dict[str, Any]], int]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in subs:
        if not isinstance(s, dict):
            continue
        key = _subject_name_key(s.get("name"))
        buckets[key].append(s)

    removed = 0
    keepers: list[dict[str, Any]] = []
    for key, group in buckets.items():
        if not group:
            continue
        if not key:
            # keep all unnamed/blank entries as-is (no name-based merge)
            for s in group:
                keepers.append(_copy_subject_entry(s))
            continue
        if len(group) == 1:
            keepers.append(_copy_subject_entry(group[0]))
        else:
            keepers.append(_copy_subject_entry(_pick_subject_to_keep(group)))
            removed += len(group) - 1

    keepers.sort(key=lambda x: str(x.get("name", "")).lower())
    return keepers, removed


def _dedupe_subjects_in_classes(
    classes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    total_removed = 0
    out: list[dict[str, Any]] = []
    for c in classes:
        subs = c.get("subjects") or []
        if not isinstance(subs, list):
            subs = []
        deduped, n = _dedupe_subjects_in_class(subs)
        total_removed += n
        out.append(
            {
                **c,
                "subjects": deduped,
            }
        )
    return out, total_removed


def _copy_subject_entry(s: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(s.get("id", "") or uuid.uuid4()),
        "name": str(s.get("name", "")),
    }
    if s.get("curriculum_subject_id") is not None:
        out["curriculum_subject_id"] = s["curriculum_subject_id"]
    return out


def _normalize_classes(classes: Any) -> list[dict[str, Any]]:
    if not isinstance(classes, list):
        return []
    out: list[dict[str, Any]] = []
    for c in classes:
        if not isinstance(c, dict):
            continue
        subs_out: list[dict[str, Any]] = []
        for s in c.get("subjects") or []:
            if isinstance(s, dict) and s.get("id"):
                subs_out.append(_copy_subject_entry(s))
        out.append(
            {
                "id": str(c.get("id", "") or uuid.uuid4()),
                "name": str(c.get("name", "") or "Class"),
                "subjects": subs_out,
            }
        )
    return out


def _merge_legacy_into_first_class(
    classes: list[dict[str, Any]], legacy: list[Any]
) -> list[dict[str, Any]]:
    if not classes:
        classes = [
            {
                "id": str(uuid.uuid4()),
                "name": "Default class",
                "subjects": [],
            }
        ]
    first = classes[0]
    subs = list(first.get("subjects") or [])
    if not isinstance(subs, list):
        subs = []
    existing = {str(s.get("id", "")) for s in subs if isinstance(s, dict) and s.get("id")}
    for s in legacy:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "") or uuid.uuid4())
        if sid in existing:
            continue
        existing.add(sid)
        subs.append(_copy_subject_entry({**s, "id": sid}))
    first = dict(first)
    first["subjects"] = subs
    classes = list(classes)
    classes[0] = first
    return classes


async def main() -> None:
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client.get_default_database()
    coll = db["organizations"]

    root_cleaned = 0
    total_duplicates_removed = 0
    cursor = coll.find({})
    async for doc in cursor:
        legacy = doc.get("subjects")
        has_root = "subjects" in doc
        classes_raw = doc.get("classes")
        new_classes = _normalize_classes(classes_raw)

        if isinstance(legacy, list) and len(legacy) > 0:
            new_classes = _merge_legacy_into_first_class(new_classes, legacy)

        new_classes, n_dup = _dedupe_subjects_in_classes(new_classes)
        total_duplicates_removed += n_dup

        need_write = has_root or n_dup > 0
        if not need_write:
            continue

        update: dict[str, Any] = {"$set": {"classes": new_classes}}
        if has_root:
            update["$unset"] = {"subjects": ""}
        await coll.update_one({"_id": doc["_id"]}, update)
        if has_root:
            root_cleaned += 1

    print(f"Cleaned {root_cleaned} organization document(s) (removed root-level subjects).")
    print(f"Removed {total_duplicates_removed} duplicate subjects")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
