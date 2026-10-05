"""
Structured test seed: Science → Is Matter Around Us Pure, concept-scoped notes + question bank.

Resolves organization_id from (in order):
  1. SEED_USER_EMAIL — first User with this email (uses user.organization_id)
  2. SEED_ORGANIZATION_ID — 24-char hex ObjectId

Optional:
  SEED_REPLACE=0 — skip deleting existing notes/questions for this topic
  (default: 1 = replace)

Run from `backend`:
  python -m app.scripts.seed_science_structured

  # Example:
  set SEED_USER_EMAIL=you@example.com
  python -m app.scripts.seed_science_structured
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from beanie.odm.fields import PydanticObjectId

from app.core.config import Settings
from app.core.database import connect_to_mongo
from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.subjects import Subject
from app.models.curriculum.topics import Topic
from app.models.identification.users import User


async def _resolve_organization_id() -> PydanticObjectId:
    email = os.environ.get("SEED_USER_EMAIL", "").strip()
    if email:
        user = await User.find_one(User.email == email)
        if user is None:
            print(f"ERROR: No user with email {email!r}", file=sys.stderr)
            sys.exit(1)
        return user.organization_id

    raw = os.environ.get("SEED_ORGANIZATION_ID", "").strip()
    if raw and len(raw) == 24:
        return PydanticObjectId(raw)

    users = await User.find().limit(1).to_list()
    user = users[0] if users else None
    if user is not None:
        print(
            f"Using organization_id from first user in DB (email={user.email}). "
            "Set SEED_USER_EMAIL or SEED_ORGANIZATION_ID to be explicit."
        )
        return user.organization_id

    print(
        "ERROR: Set SEED_USER_EMAIL or SEED_ORGANIZATION_ID, or register at least one user.",
        file=sys.stderr,
    )
    sys.exit(1)


async def seed() -> dict[str, Any]:
    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)

    organization_id = await _resolve_organization_id()
    replace = os.environ.get("SEED_REPLACE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    subject = await Subject.find_one(
        Subject.organization_id == organization_id,
        Subject.name == "Science",
    )
    if subject is None:
        subject = Subject(
            organization_id=organization_id,
            name="Science",
            grade="9",
            board="general",
            description="General science concepts for school students",
            academic_year="2024",
            curriculum_version="v1",
            status="active",
            is_active=True,
        )
        await subject.insert()
        subject_action = "created"
    else:
        subject_action = "existing"

    topic_slug = "is-matter-around-us-pure"
    topic = await Topic.find_one(
        Topic.organization_id == organization_id,
        Topic.topic_slug == topic_slug,
    )
    key_concepts = [
        "matter",
        "pure substance",
        "mixture",
        "types of mixtures",
        "solution",
        "suspension",
        "colloid",
    ]
    if topic is None:
        topic = Topic(
            organization_id=organization_id,
            subject_id=subject.id,
            topic_name="Is Matter Around Us Pure",
            topic_slug=topic_slug,
            topic_description=(
                "Understanding matter, pure substances, mixtures, and types of mixtures "
                "like solutions, suspensions, and colloids."
            ),
            learning_objectives=[],
            learning_outcomes=[],
            key_concepts=key_concepts,
            common_mistakes=[],
            difficulty_level="basic",
            topic_order=1,
            estimated_time=45,
            default_depth="basic",
            academic_year="2024",
            curriculum_version="v1",
            status="active",
            is_active=True,
        )
        await topic.insert()
        topic_action = "created"
    else:
        topic.key_concepts = key_concepts
        await topic.save()
        topic_action = "updated"

    topic_id = topic.id
    if replace:
        await TopicNote.find(TopicNote.topic_id == topic_id).delete()
        await TopicQuestionBank.find(TopicQuestionBank.topic_id == topic_id).delete()
    elif await TopicNote.find_one(TopicNote.topic_id == topic_id) is not None:
        print(
            "Science topic already has notes. Set SEED_REPLACE=1 to wipe and re-insert.",
            file=sys.stderr,
        )
        sys.exit(1)

    notes_specs: list[dict[str, Any]] = [
        {
            "note_type": "summary",
            "concept": None,
            "content_markdown": (
                "Matter is anything that has mass and occupies space. In daily life, we "
                "see different types of matter, some are pure while others are mixtures. "
                "This chapter helps us understand the difference between pure substances "
                "and mixtures."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "pure substance",
            "content_markdown": (
                "A pure substance is made up of only one type of particle and has a fixed "
                "composition. Examples include elements like oxygen and compounds like water."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "mixture",
            "content_markdown": (
                "A mixture is a combination of two or more substances that are not "
                "chemically combined. The components can be separated by physical methods."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "solution",
            "content_markdown": (
                "A solution is a homogeneous mixture in which one substance (solute) is "
                "dissolved in another (solvent). For example, salt dissolved in water."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "suspension",
            "content_markdown": (
                "A suspension is a heterogeneous mixture in which particles are large enough "
                "to settle down when left undisturbed. For example, muddy water."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "colloid",
            "content_markdown": (
                "A colloid is a mixture where particles are smaller than in suspensions but "
                "do not settle down. Examples include milk and fog."
            ),
        },
    ]

    notes_out: list[str] = []
    for spec in notes_specs:
        note = TopicNote(
            organization_id=organization_id,
            topic_id=topic_id,
            grade="9",
            board="general",
            note_type=spec["note_type"],
            content_markdown=spec["content_markdown"],
            source_type="teacher",
            teaching_style=None,
            interest_category=None,
            difficulty_level="basic",
            approved=True,
            usage_count=0,
            concept=spec["concept"],
        )
        await note.insert()
        notes_out.append(str(note.id))

    bank_specs: list[dict[str, Any]] = [
        {
            "concept": "pure substance",
            "question_text": "What is a pure substance?",
            "correct_answer": (
                "A substance made of only one type of particle with fixed composition."
            ),
            "options": [
                "A substance made of only one type of particle with fixed composition.",
                "A random mix of many particles.",
                "Anything that is liquid.",
                "A substance that always settles down.",
            ],
            "explanation": (
                "Pure substances have one type of particle and fixed composition."
            ),
            "difficulty_level": 1,
        },
        {
            "concept": "mixture",
            "question_text": "What is a mixture?",
            "correct_answer": (
                "A combination of two or more substances that are not chemically combined."
            ),
            "options": [
                "A combination of two or more substances that are not chemically combined.",
                "A single pure element only.",
                "Only a homogeneous liquid.",
                "A compound with fixed composition only.",
            ],
            "explanation": (
                "Mixtures combine substances physically; components can be separated."
            ),
            "difficulty_level": 1,
        },
        {
            "concept": "solution",
            "question_text": "Give an example of a solution.",
            "correct_answer": "Salt dissolved in water.",
            "options": [
                "Salt dissolved in water.",
                "Muddy water.",
                "Oil and water layers.",
                "Dry sand and stones.",
            ],
            "explanation": (
                "A solution is homogeneous; salt in water is a standard example."
            ),
            "difficulty_level": 1,
        },
        {
            "concept": "suspension",
            "question_text": (
                "What happens to particles in a suspension when left undisturbed?"
            ),
            "correct_answer": "They settle down.",
            "options": [
                "They settle down.",
                "They dissolve completely.",
                "They disappear.",
                "They become pure substance.",
            ],
            "explanation": (
                "Suspension particles are large enough to settle on standing."
            ),
            "difficulty_level": 1,
        },
        {
            "concept": "colloid",
            "question_text": "Give an example of a colloid.",
            "correct_answer": "Milk.",
            "options": [
                "Milk.",
                "Salt crystal.",
                "Pure oxygen.",
                "Distilled water.",
            ],
            "explanation": "Milk is a classic colloid and does not settle easily.",
            "difficulty_level": 1,
        },
    ]

    questions_out: list[str] = []
    for spec in bank_specs:
        q = TopicQuestionBank(
            organization_id=organization_id,
            topic_id=topic_id,
            difficulty_level=spec["difficulty_level"],
            question_text=spec["question_text"],
            options=spec["options"],
            correct_answer=spec["correct_answer"],
            explanation=spec["explanation"],
            approved=True,
            usage_count=0,
            concept=spec["concept"],
            question_type="mcq",
            quiz_stage="concept_check",
        )
        await q.insert()
        questions_out.append(str(q.id))

    report = {
        "organization_id": str(organization_id),
        "subject": {
            "id": str(subject.id),
            "name": subject.name,
            "action": subject_action,
        },
        "topic": {
            "id": str(topic.id),
            "name": topic.topic_name,
            "key_concepts": topic.key_concepts,
            "action": topic_action,
        },
        "notes_inserted": notes_out,
        "questions_inserted": questions_out,
        "replaced_existing_content": replace,
    }

    print("--- Structured Science seed complete ---")
    print(f"organization_id: {report['organization_id']}")
    print(f"subject: {report['subject']}")
    print(f"topic: {report['topic']}")
    print(f"notes ({len(notes_out)}): {notes_out}")
    print(f"questions ({len(questions_out)}): {questions_out}")
    return report


if __name__ == "__main__":
    asyncio.run(seed())
