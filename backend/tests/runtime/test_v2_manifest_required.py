"""Published v2 topics must not silently fall back to legacy key_concepts."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.main import app
from app.models.curriculum.topics import Topic
from app.services.runtime.curriculum_resolution_service import CurriculumResolutionError


@pytest.fixture
async def student_api(db, student_user, student_token):
    app.dependency_overrides[get_current_user] = lambda: student_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {student_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_v2_published_start_fails_when_manifest_resolution_fails(
    db,
    student_api,
    org,
):
    topic = Topic(
        organization_id=org.id,
        subject_id=PydanticObjectId(),
        topic_name="Broken V2",
        topic_slug="broken-v2",
        topic_description="Published v2 with broken tree",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=30,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        curriculum_revision=1,
        curriculum_published_at=datetime.now(timezone.utc),
        key_concepts=["legacy_only"],
    )
    await topic.insert()

    with patch(
        "app.api.routes.sessions.CurriculumResolutionService.resolve_published_topic_v2",
        new_callable=AsyncMock,
        side_effect=CurriculumResolutionError("EMPTY_CURRICULUM", "No concepts"),
    ):
        res = await student_api.post(
            "/sessions/start",
            json={"topic_id": str(topic.id)},
        )
    assert res.status_code == 400
    body = res.json()
    assert body["detail"]["code"] == "EMPTY_CURRICULUM"
