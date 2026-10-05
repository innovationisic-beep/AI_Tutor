"""Resolve catalog vs teacher topic context for curriculum authoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.curriculum.curriculum_enums import CurriculumSchemaVersion, TopicSource
from app.models.curriculum.topics import Topic
from app.models.identification.users import User
from app.models.teacher_topic import TeacherTopic


@dataclass(frozen=True)
class TopicContext:
    topic_id: PydanticObjectId
    topic_source: TopicSource
    organization_id: Optional[PydanticObjectId]
    topic_name: str
    curriculum_schema_version: CurriculumSchemaVersion
    curriculum_revision: int
    curriculum_published_at: Optional[datetime]
    supports_class_sessions: bool
    is_catalog: bool


def effective_supports_class_sessions(
    *,
    curriculum_schema_version: CurriculumSchemaVersion,
    curriculum_published_at: Optional[datetime],
    stored_flag: bool,
) -> bool:
    """Published v2 topics always support class sessions (incl. pre-3B.1B rows)."""
    if stored_flag:
        return True
    return (
        curriculum_schema_version == "v2" and curriculum_published_at is not None
    )


async def _backfill_supports_class_sessions_if_needed(
    topic: TeacherTopic | Topic,
    *,
    effective: bool,
) -> None:
    if not effective or bool(topic.supports_class_sessions):
        return
    topic.supports_class_sessions = True
    await topic.save()


def _context_from_teacher_topic(tt: TeacherTopic) -> TopicContext:
    supports = effective_supports_class_sessions(
        curriculum_schema_version=tt.curriculum_schema_version,
        curriculum_published_at=tt.curriculum_published_at,
        stored_flag=bool(tt.supports_class_sessions),
    )
    return TopicContext(
        topic_id=tt.id,
        topic_source="teacher",
        organization_id=tt.organization_id,
        topic_name=tt.topic_name,
        curriculum_schema_version=tt.curriculum_schema_version,
        curriculum_revision=int(tt.curriculum_revision or 0),
        curriculum_published_at=tt.curriculum_published_at,
        supports_class_sessions=supports,
        is_catalog=False,
    )


def _context_from_catalog_topic(topic: Topic) -> TopicContext:
    supports = effective_supports_class_sessions(
        curriculum_schema_version=topic.curriculum_schema_version,
        curriculum_published_at=topic.curriculum_published_at,
        stored_flag=bool(topic.supports_class_sessions),
    )
    return TopicContext(
        topic_id=topic.id,
        topic_source="catalog",
        organization_id=topic.organization_id,
        topic_name=topic.topic_name,
        curriculum_schema_version=topic.curriculum_schema_version,
        curriculum_revision=int(topic.curriculum_revision or 0),
        curriculum_published_at=topic.curriculum_published_at,
        supports_class_sessions=supports,
        is_catalog=topic.organization_id is None,
    )


async def resolve_topic_context(
    topic_id: PydanticObjectId,
    topic_source: TopicSource,
    user: User,
    *,
    require_mutation_access: bool = True,
) -> TopicContext:
    if topic_source == "teacher":
        topic = await TeacherTopic.get(topic_id)
        if topic is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Topic not found",
            )
        if require_mutation_access:
            if user.organization_id is None or topic.organization_id != user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Topic not in your organization",
                )
            if user.role == "teacher" and topic.teacher_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only edit your own topics",
                )
            if user.role not in ("teacher", "admin"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not allowed",
                )
        ctx = _context_from_teacher_topic(topic)
        await _backfill_supports_class_sessions_if_needed(
            topic, effective=ctx.supports_class_sessions
        )
        return ctx

    topic = await Topic.get(topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )
    if topic.organization_id is not None:
        if require_mutation_access and user.organization_id != topic.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Catalog topic not in your organization",
            )
    elif require_mutation_access and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for platform catalog topics",
        )
    ctx = _context_from_catalog_topic(topic)
    await _backfill_supports_class_sessions_if_needed(
        topic, effective=ctx.supports_class_sessions
    )
    return ctx


async def topic_context_from_teacher_topic(tt: TeacherTopic) -> TopicContext:
    return _context_from_teacher_topic(tt)


async def topic_context_from_catalog_topic(topic: Topic) -> TopicContext:
    return _context_from_catalog_topic(topic)


async def save_topic_curriculum_metadata(
    ctx: TopicContext,
    *,
    curriculum_revision: Optional[int] = None,
    curriculum_published_at: Optional[datetime] = None,
    clear_curriculum_published_at: bool = False,
) -> None:
    if ctx.topic_source == "teacher":
        doc = await TeacherTopic.get(ctx.topic_id)
        if doc is None:
            return
        if curriculum_revision is not None:
            doc.curriculum_revision = curriculum_revision
        if clear_curriculum_published_at:
            doc.curriculum_published_at = None
        elif curriculum_published_at is not None:
            doc.curriculum_published_at = curriculum_published_at
        await doc.save()
        return

    doc = await Topic.get(ctx.topic_id)
    if doc is None:
        return
    if curriculum_revision is not None:
        doc.curriculum_revision = curriculum_revision
    if clear_curriculum_published_at:
        doc.curriculum_published_at = None
    elif curriculum_published_at is not None:
        doc.curriculum_published_at = curriculum_published_at
    await doc.save()


async def set_topic_schema_version(
    ctx: TopicContext,
    version: Literal["v1", "v2"],
) -> None:
    if ctx.topic_source == "teacher":
        doc = await TeacherTopic.get(ctx.topic_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        doc.curriculum_schema_version = version
        await doc.save()
        return
    doc = await Topic.get(ctx.topic_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    doc.curriculum_schema_version = version
    await doc.save()
