"""
Remove curriculum documents that do not match the Beanie Subject/Topic schema
(e.g. old docs using subject_name instead of name). Safe to run before seed_curriculum.

Usage (from backend directory):
  python -m scripts.remove_legacy_curriculum

Optional: set CURRICULUM_ORG_ID to only delete docs for one org; otherwise cleans all
legacy-shaped subjects/topics in the database.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.core.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient


async def main() -> None:
    settings = Settings()
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client.get_default_database()
    org_match: dict | None = None
    raw_org = os.environ.get("CURRICULUM_ORG_ID", "").strip()
    if raw_org:
        from beanie.odm.fields import PydanticObjectId

        # DB may store organization_id as ObjectId or string (legacy / manual inserts)
        oid = PydanticObjectId(raw_org)
        org_match = {
            "$or": [
                {"organization_id": oid},
                {"organization_id": raw_org},
            ]
        }
        print(f"Scoping to organization_id={raw_org}")

    subject_legacy_shape = {
        "$or": [
            {"name": {"$exists": False}},
            {"subject_name": {"$exists": True}},
        ]
    }
    legacy_subject_q: dict = (
        {"$and": [org_match, subject_legacy_shape]}
        if org_match is not None
        else subject_legacy_shape
    )
    sr = await db["subjects"].delete_many(legacy_subject_q)
    print(f"Deleted {sr.deleted_count} legacy subject document(s).")

    topic_legacy_shape = {
        "$or": [
            {"topic_name": {"$exists": False}},
            {"topic_slug": {"$exists": False}},
        ]
    }
    legacy_topic_q: dict = (
        {"$and": [org_match, topic_legacy_shape]}
        if org_match is not None
        else topic_legacy_shape
    )
    tr = await db["topics"].delete_many(legacy_topic_q)
    print(f"Deleted {tr.deleted_count} legacy/incomplete topic document(s).")

    client.close()
    print("Done. Run: python -m scripts.seed_curriculum (with CURRICULUM_ORG_ID if needed).")


if __name__ == "__main__":
    asyncio.run(main())
