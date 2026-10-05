"""
Structured test seed: Math → Fractions, concept-scoped notes + question bank.

Resolves organization_id from (in order):
  1. SEED_USER_EMAIL — first User with this email (uses user.organization_id)
  2. SEED_ORGANIZATION_ID — 24-char hex ObjectId

Optional:
  SEED_REPLACE=0 — skip deleting existing notes/questions for the Fractions topic (default: 1 = replace)

Run from `backend`:
  python -m app.scripts.seed_fractions_structured

  # Example with a registered account:
  set SEED_USER_EMAIL=you@example.com
  python -m app.scripts.seed_fractions_structured
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
    replace = os.environ.get("SEED_REPLACE", "1").strip() not in ("0", "false", "no")

    subject = await Subject.find_one(
        Subject.organization_id == organization_id,
        Subject.name == "Math",
    )
    if subject is None:
        subject = Subject(
            organization_id=organization_id,
            name="Math",
            grade="6",
            board="general",
            description="Basic mathematics concepts",
            academic_year="2024",
            curriculum_version="v1",
            status="active",
            is_active=True,
        )
        await subject.insert()
        subject_action = "created"
    else:
        subject_action = "existing"

    topic = await Topic.find_one(
        Topic.organization_id == organization_id,
        Topic.topic_slug == "fractions",
    )
    key_concepts = [
        "fraction",
        "numerator",
        "denominator",
        "addition of fractions",
    ]
    if topic is None:
        topic = Topic(
            organization_id=organization_id,
            subject_id=subject.id,
            topic_name="Fractions",
            topic_slug="fractions",
            topic_description=(
                "Understanding fractions: numerator, denominator, and adding fractions "
                "with a common denominator."
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
            "Fractions topic already has notes. Set SEED_REPLACE=1 to wipe and re-insert, "
            "or delete topic content manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    notes_specs: list[dict[str, Any]] = [
        {
            "note_type": "summary",
            "concept": None,
            "content_markdown": (
                "A fraction represents a part of a whole. It is written as two numbers "
                "separated by a slash. The top number is called the numerator and the "
                "bottom number is called the denominator."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "numerator",
            "content_markdown": (
                "The numerator is the top number in a fraction. It tells how many parts "
                "we are considering."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "denominator",
            "content_markdown": (
                "The denominator is the bottom number in a fraction. It tells how many "
                "equal parts the whole is divided into."
            ),
        },
        {
            "note_type": "detailed",
            "concept": "addition of fractions",
            "content_markdown": (
                "To add fractions with the same denominator, add the numerators and keep "
                "the denominator the same. For example, 2/5 + 1/5 = 3/5."
            ),
        },
    ]

    notes_out: list[str] = []
    for spec in notes_specs:
        note = TopicNote(
            organization_id=organization_id,
            topic_id=topic_id,
            grade="6",
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
            "concept": "numerator",
            "question_text": "In the fraction 3/5, what is the numerator?",
            "correct_answer": "3",
            "options": ["3", "5", "8", "35"],
            "explanation": "The numerator is the top number; in 3/5 it is 3.",
            "difficulty_level": 1,
        },
        {
            "concept": "denominator",
            "question_text": "In the fraction 3/5, what is the denominator?",
            "correct_answer": "5",
            "options": ["5", "3", "15", "8"],
            "explanation": "The denominator is the bottom number; in 3/5 it is 5.",
            "difficulty_level": 1,
        },
        {
            "concept": "addition of fractions",
            "question_text": "What is 2/5 + 1/5?",
            "correct_answer": "3/5",
            "options": ["3/5", "3/10", "2/5", "1/5"],
            "explanation": "Same denominator: add numerators 2+1=3, keep denominator 5.",
            "difficulty_level": 1,
        },
        {
            "concept": "addition of fractions",
            "question_text": "What is 3/4 + 2/4?",
            "correct_answer": "5/4",
            "options": ["5/4", "5/8", "1", "6/8"],
            "explanation": "Add numerators 3+2=5; denominator stays 4, so 5/4.",
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

    print("--- Structured Fractions seed complete ---")
    print(f"organization_id: {report['organization_id']}")
    print(f"subject: {report['subject']}")
    print(f"topic: {report['topic']}")
    print(f"notes ({len(notes_out)}): {notes_out}")
    print(f"questions ({len(questions_out)}): {questions_out}")
    return report


if __name__ == "__main__":
    asyncio.run(seed())
