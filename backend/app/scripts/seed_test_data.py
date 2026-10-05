"""
Seed MongoDB with test data for the AI Tutor (Fractions topic, notes, questions, video, subtitles).

Prerequisites:
  Set environment variables (24-char hex ObjectIds from your DB):
    SEED_ORGANIZATION_ID  — existing organization _id
    SEED_SUBJECT_ID       — existing subject _id
    SEED_TEACHER_USER_ID  — existing user _id (teacher) for Video.uploaded_by_teacher_id

  Optional:
    SEED_STUDENT_ID       — if set, creates a baseline MasteryRecord for that student + topic

  MONGODB_URL defaults from app config (e.g. mongodb://localhost:27017/ai_tutor).

Run from the `backend` directory:
  python -m app.scripts.seed_test_data
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from beanie.odm.fields import PydanticObjectId

from app.core.config import Settings
from app.core.database import connect_to_mongo
from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.content.video_subtitles import VideoSubtitle
from app.models.content.videos import Video
from app.models.curriculum.topics import Topic
from app.models.learning.mastery_records import MasteryRecord, mastery_record_filter


def _require_oid(name: str) -> PydanticObjectId:
    raw = os.environ.get(name, "").strip()
    if not raw or raw.startswith("PUT_") or len(raw) != 24:
        print(
            f"ERROR: Set a valid 24-char hex {name} in the environment "
            f"(e.g. export {name}=... )",
            file=sys.stderr,
        )
        sys.exit(1)
    return PydanticObjectId(raw)


async def seed() -> None:
    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)

    organization_id = _require_oid("SEED_ORGANIZATION_ID")
    subject_id = _require_oid("SEED_SUBJECT_ID")
    teacher_user_id = _require_oid("SEED_TEACHER_USER_ID")

    existing = await Topic.find_one(
        {"organization_id": organization_id, "topic_slug": "fractions"}
    )
    if existing is not None:
        print(
            f"Topic with slug 'fractions' already exists (topic_id={existing.id}). "
            "Remove it first or change the slug in this script to re-seed.",
            file=sys.stderr,
        )
        sys.exit(1)

    topic = Topic(
        organization_id=organization_id,
        subject_id=subject_id,
        topic_name="Fractions",
        topic_slug="fractions",
        topic_description=(
            "Understanding fractions, numerators, denominators and basic operations"
        ),
        difficulty_level="basic",
        topic_order=1,
        estimated_time=30,
        default_depth="basic",
        academic_year="2024",
        curriculum_version="v1",
        key_concepts=[
            "fraction",
            "numerator",
            "denominator",
            "half",
            "part of whole",
        ],
        status="active",
        is_active=True,
    )
    await topic.insert()
    topic_id = topic.id

    notes_data: list[dict] = [
        {
            "note_type": "summary",
            "content_markdown": (
                "A fraction represents a part of a whole. It has two parts: "
                "numerator and denominator."
            ),
        },
        {
            "note_type": "detailed",
            "content_markdown": (
                "Imagine a pizza divided into 4 slices. Each slice is 1/4. "
                "The top number is numerator..."
            ),
        },
        {
            "note_type": "revision",
            "content_markdown": "Fraction = part of whole. Example: 1/2, 3/4.",
        },
    ]

    notes_created = 0
    for spec in notes_data:
        note = TopicNote(
            organization_id=organization_id,
            topic_id=topic_id,
            grade="6",
            board="local",
            note_type=spec["note_type"],
            content_markdown=spec["content_markdown"],
            source_type="teacher",
            teaching_style="story",
            interest_category="sports",
            difficulty_level="basic",
            approved=True,
            usage_count=0,
        )
        await note.insert()
        notes_created += 1

    bank_specs: list[tuple[str, int]] = [
        ("What is 1/2 of 8?", 1),
        ("What is numerator?", 1),
        ("What is denominator?", 1),
        ("What is 3/4 of 12?", 2),
        ("Add 1/2 + 1/2", 2),
    ]

    questions_created = 0
    for qtext, diff in bank_specs:
        q = TopicQuestionBank(
            organization_id=organization_id,
            topic_id=topic_id,
            difficulty_level=diff,
            question_text=qtext,
            options=["A", "B", "C", "D"],
            correct_answer="See explanation",
            explanation=(
                "Seed answer for testing. Replace with real key in production data."
            ),
            approved=True,
            usage_count=0,
            question_type="mcq",
            quiz_stage="concept_check",
        )
        # Tailor a few for plausibility
        if "1/2 of 8" in qtext:
            q.options = ["2", "4", "6", "8"]
            q.correct_answer = "4"
            q.explanation = "Half of eight is four."
        elif "numerator" in qtext.lower():
            q.options = ["bottom number", "top number", "the line", "the whole"]
            q.correct_answer = "top number"
            q.explanation = "The numerator is the top number in a fraction."
        elif "denominator" in qtext.lower():
            q.options = ["top number", "bottom number", "the line", "the part"]
            q.correct_answer = "bottom number"
            q.explanation = "The denominator is the bottom number."
        elif "3/4 of 12" in qtext:
            q.options = ["6", "9", "8", "12"]
            q.correct_answer = "9"
            q.explanation = "Three quarters of 12 is 9."
        elif "1/2 + 1/2" in qtext:
            q.options = ["1/4", "1/2", "1", "2"]
            q.correct_answer = "1"
            q.explanation = "One half plus one half equals one whole."

        await q.insert()
        questions_created += 1

    video = Video(
        organization_id=organization_id,
        topic_id=topic_id,
        title="Fractions Basics",
        description="Introductory video on fractions for testing.",
        video_url="https://example.com/seed/fractions-basics.mp4",
        duration_seconds=600,
        grade="6",
        board="local",
        status="approved",
        uploaded_by_teacher_id=teacher_user_id,
    )
    await video.insert()

    subtitle_texts = [
        "Imagine a football match divided into two halves...",
        "Each half represents 1/2 of the total time.",
    ]
    subtitles_created = 0
    for idx, text in enumerate(subtitle_texts):
        sub = VideoSubtitle(
            organization_id=organization_id,
            video_id=video.id,
            start_time=float(idx * 60),
            end_time=float((idx + 1) * 60),
            text=text,
            chunk_index=idx,
        )
        await sub.insert()
        subtitles_created += 1

    student_raw = os.environ.get("SEED_STUDENT_ID", "").strip()
    if student_raw and len(student_raw) == 24 and not student_raw.startswith("PUT_"):
        student_id = PydanticObjectId(student_raw)
        m_existing = await MasteryRecord.find_one(
            mastery_record_filter(organization_id, student_id, topic_id, None)
        )
        if m_existing is None:
            now = datetime.utcnow()
            mastery = MasteryRecord(
                organization_id=organization_id,
                student_id=student_id,
                topic_id=topic_id,
                concept=None,
                mastery_score=50.0,
                confidence_score=0.0,
                teachback_average=0.0,
                engagement_score=0.0,
                revision_needed=False,
                attempt_count=0,
                last_session_id=None,
                last_updated=now,
            )
            await mastery.insert()
            print(f"Optional MasteryRecord created for student_id={student_id}")
        else:
            print(
                f"Skipping MasteryRecord (already exists for student_id={student_id})"
            )

    print("--- Seed complete ---")
    print(f"topic_id: {topic_id}")
    print(f"notes created: {notes_created}")
    print(f"questions created: {questions_created}")
    print(f"video_id: {video.id}")
    print(f"subtitles created: {subtitles_created}")


if __name__ == "__main__":
    asyncio.run(seed())
