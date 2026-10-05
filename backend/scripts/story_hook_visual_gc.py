"""
Sweep Story Hook visual binaries that no concept references.

Uploads commit bytes before the author saves the concept, so an abandoned form
can leave an unreferenced object behind. Only objects older than
``--min-age-hours`` are removed, so an upload in progress is never collected.

Run from the backend dir:
    python -m scripts.story_hook_visual_gc --dry-run
    python -m scripts.story_hook_visual_gc --min-age-hours 24
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import Settings
from app.services.storage.story_hook_storage import LocalStoryHookStorage


async def referenced_storage_keys(db) -> set[str]:
    keys: set[str] = set()
    cursor = db["curriculum_concepts"].find(
        {"story_hook.visuals": {"$exists": True, "$ne": []}},
        {"story_hook.visuals.storage_key": 1},
    )
    async for row in cursor:
        for visual in ((row.get("story_hook") or {}).get("visuals") or []):
            key = str((visual or {}).get("storage_key") or "").strip()
            if key:
                keys.add(key)
    return keys


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-age-hours", type=float, default=24.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    if settings.STORY_HOOK_STORAGE_PROVIDER.strip().lower() != "local":
        raise SystemExit(
            "This sweeper only supports the local provider; use the object "
            "store's own lifecycle rules in production."
        )

    storage = LocalStoryHookStorage(settings.STORY_HOOK_LOCAL_ROOT)
    root = storage.root
    if not root.is_dir():
        print(f"Storage root does not exist yet: {root}")
        return

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        referenced = await referenced_storage_keys(client.get_default_database())
    finally:
        client.close()

    cutoff = time.time() - args.min_age_hours * 3600
    removed = 0
    kept = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.endswith(".part"):
            continue
        key = path.relative_to(root).as_posix()
        if key in referenced:
            kept += 1
            continue
        if path.stat().st_mtime > cutoff:
            kept += 1
            continue
        print(f"{'[dry-run] would delete' if args.dry_run else 'deleting'} {key}")
        if not args.dry_run:
            await storage.delete(key)
        removed += 1

    print(
        f"referenced={len(referenced)} kept={kept} "
        f"{'would_remove' if args.dry_run else 'removed'}={removed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
