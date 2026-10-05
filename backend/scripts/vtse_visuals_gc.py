"""Sweep VTSE image binaries that no concept references.

Run from the backend dir:
    python -m scripts.vtse_visuals_gc --dry-run
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
from app.services.storage.visual_teaching_storage import LocalVisualTeachingStorage


async def referenced_storage_keys(db) -> set[str]:
    keys: set[str] = set()
    cursor = db["curriculum_concepts"].find(
        {"vtse_visuals.images": {"$exists": True, "$ne": []}},
        {"vtse_visuals.images.storage_key": 1},
    )
    async for row in cursor:
        for image in ((row.get("vtse_visuals") or {}).get("images") or []):
            key = str((image or {}).get("storage_key") or "").strip()
            if key:
                keys.add(key)
    return keys


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-age-hours", type=float, default=24.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    provider = str(getattr(settings, "VTSE_VISUALS_STORAGE_PROVIDER", "local") or "local")
    if provider.strip().lower() != "local":
        raise SystemExit("This sweeper only supports the local provider.")
    root_path = LocalVisualTeachingStorage(settings.VTSE_VISUALS_LOCAL_ROOT).root
    if not root_path.is_dir():
        print(f"Storage root does not exist yet: {root_path}")
        return
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        referenced = await referenced_storage_keys(client.get_default_database())
    finally:
        client.close()
    cutoff = time.time() - args.min_age_hours * 3600
    removed = 0
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(root_path).as_posix()
        if key in referenced or path.stat().st_mtime > cutoff:
            continue
        removed += 1
        print(("would remove " if args.dry_run else "removed ") + key)
        if not args.dry_run:
            path.unlink()
    print(f"done removed={removed}")


if __name__ == "__main__":
    asyncio.run(main())
