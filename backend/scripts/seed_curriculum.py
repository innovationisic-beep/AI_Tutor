"""
Seed script: insert test curriculum data (1 subject, 4 topics, 3 progression edges).
Uses the same organization_id as existing records. Run from backend dir:
  python -m scripts.seed_curriculum
"""
import asyncio
import os
import sys
from datetime import datetime

# Run from backend directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beanie.odm.fields import PydanticObjectId
from dotenv import load_dotenv

load_dotenv()

from app.core.config import Settings
from app.core.database import connect_to_mongo
from app.models.curriculum.subjects import Subject
from app.models.curriculum.topic_progression_map import TopicProgressionMap
from app.models.curriculum.topics import Topic
from app.models.identification.organizations import Organization


async def get_organization_id() -> PydanticObjectId:
    """
    Resolve org for seeding:
    1) CURRICULUM_ORG_ID env (recommended: set to your user's organization_id from /users/me)
    2) First organization in the database
    3) Fallback: from first subject or user
    """
    raw = os.environ.get("CURRICULUM_ORG_ID", "").strip()
    if raw:
        try:
            oid = PydanticObjectId(raw)
            org = await Organization.get(oid)
            if org is None:
                print(
                    f"WARNING: No Organization document for id={raw}; "
                    "seeding curriculum for this org_id anyway (repair / orphaned user org)."
                )
            else:
                print(f"Using CURRICULUM_ORG_ID from environment: {oid}")
            return oid
        except Exception as e:
            raise RuntimeError(f"Invalid CURRICULUM_ORG_ID: {e}") from e

    org = await Organization.find_one()
    if org is not None:
        return org.id
    # Fallback: from first subject or user
    subject = await Subject.find_one()
    if subject is not None:
        return subject.organization_id
    from app.models.identification.users import User

    user = await User.find_one()
    if user is not None:
        return user.organization_id
    raise RuntimeError(
        "No existing organization found. Create an organization (e.g. via register) first."
    )


async def seed() -> None:
    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)
    org_id = await get_organization_id()
    print(f"Using organization_id: {org_id}")

    # 1. Subject: Mathematics (grade 6)
    subject = await Subject.find_one(
        {"organization_id": org_id, "name": "Mathematics", "grade": "6"}
    )
    if subject is None:
        subject = await Subject(
            organization_id=org_id,
            name="Mathematics",
            grade="6",
            board="General",
            description="Grade 6 Mathematics curriculum covering fractions, decimals, percentages, and algebra basics.",
            academic_year="2024-2025",
            curriculum_version="1.0",
            status="active",
            is_active=True,
        ).insert()
        print(f"Inserted subject: {subject.name} (id={subject.id})")
    else:
        print(f"Subject already exists: {subject.name} (id={subject.id})")

    # 2. Topics (Fractions, Decimals, Percentages, Algebra Basics)
    topic_specs = [
        ("Fractions", "fractions", "Understanding fractions, equivalence, and operations.", 0, "beginner"),
        ("Decimals", "decimals", "Decimal place value, conversion, and arithmetic.", 1, "beginner"),
        ("Percentages", "percentages", "Percentages, fractions and decimals, simple interest.", 2, "intermediate"),
        ("Algebra Basics", "algebra-basics", "Variables, expressions, and simple equations.", 3, "intermediate"),
    ]
    topic_ids: dict[str, PydanticObjectId] = {}
    for name, slug, desc, order, difficulty in topic_specs:
        existing = await Topic.find_one(
            {"organization_id": org_id, "subject_id": subject.id, "topic_slug": slug}
        )
        if existing is None:
            t = await Topic(
                organization_id=org_id,
                subject_id=subject.id,
                topic_name=name,
                topic_slug=slug,
                topic_description=desc,
                difficulty_level=difficulty,
                topic_order=order,
                estimated_time=45,
                default_depth="standard",
                academic_year="2024-2025",
                curriculum_version="1.0",
                status="active",
                is_active=True,
            ).insert()
            topic_ids[name] = t.id
            print(f"Inserted topic: {name} (id={t.id})")
        else:
            topic_ids[name] = existing.id
            print(f"Topic already exists: {name} (id={existing.id})")

    # 3. topic_progression_map edges (Fractions → Decimals, Percentages, Algebra Basics)
    edges = [
        ("Fractions", "Decimals", 60.0),
        ("Fractions", "Percentages", 70.0),
        ("Fractions", "Algebra Basics", 80.0),
    ]
    for from_name, to_name, min_mastery in edges:
        from_id = topic_ids[from_name]
        to_id = topic_ids[to_name]
        existing = await TopicProgressionMap.find_one(
            {
                "organization_id": org_id,
                "topic_id": from_id,
                "recommended_next_topic_id": to_id,
            }
        )
        if existing is None:
            await TopicProgressionMap(
                organization_id=org_id,
                topic_id=from_id,
                recommended_next_topic_id=to_id,
                minimum_mastery_to_recommend=min_mastery,
            ).insert()
            print(
                f"Inserted progression: {from_name} -> {to_name} (min_mastery={min_mastery})"
            )
        else:
            print(f"Progression already exists: {from_name} -> {to_name}")

    print("Seed completed.")


if __name__ == "__main__":
    asyncio.run(seed())
