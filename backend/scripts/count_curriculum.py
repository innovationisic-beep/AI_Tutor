"""Print subject/topic counts in MongoDB (run from backend dir: python -m scripts.count_curriculum)."""
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
    ts = await db["topics"].count_documents({})
    ss = await db["subjects"].count_documents({})
    print(f"Total subjects collection: {ss}")
    print(f"Total topics collection: {ts}")
    print("Per subject_id (topics):")
    async for row in db["topics"].aggregate(
        [{"$group": {"_id": "$subject_id", "n": {"$sum": 1}}}]
    ):
        sid = row["_id"]
        print(f"  subject_id={sid} -> {row['n']} topic document(s)")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
