"""Tests for effective_supports_class_sessions backfill."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.topics import Topic

from app.services.curriculum.topic_context_service import (
    _context_from_catalog_topic,
    effective_supports_class_sessions,
)


def test_effective_supports_class_sessions_when_published_v2():
    assert effective_supports_class_sessions(
        curriculum_schema_version="v2",
        curriculum_published_at=datetime.now(timezone.utc),
        stored_flag=False,
    )


def test_effective_supports_class_sessions_false_when_unpublished():
    assert not effective_supports_class_sessions(
        curriculum_schema_version="v2",
        curriculum_published_at=None,
        stored_flag=False,
    )


def test_topic_context_from_catalog_derives_class_sessions():
    topic = Topic.model_construct(
        id=PydanticObjectId(),
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Photosynthesis",
        topic_slug="photosynthesis",
        topic_description="Test topic for class sessions flag.",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        curriculum_revision=1,
        curriculum_published_at=datetime.now(timezone.utc),
        supports_class_sessions=False,
    )
    ctx = _context_from_catalog_topic(topic)
    assert ctx.supports_class_sessions is True
