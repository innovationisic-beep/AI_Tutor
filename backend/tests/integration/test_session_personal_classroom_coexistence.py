"""Regression: personal and classroom session flows coexist on the same topic."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.main import app
from app.models.learning.sessions import Session
from app.repositories.session_repository import SessionRepository
from app.repositories.topic_repository import TopicRepository
from app.services.session_service import SessionService
from tests.integration.test_classroom_launch import (
    _create_classroom_instance,
    _seed_zone1_cluster_a,
)


@pytest.fixture
async def classroom_api_client(db, teacher_user, teacher_token):
    app.dependency_overrides[get_current_teacher_or_admin] = lambda: teacher_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {teacher_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def student_api_client(db, student_user, student_token):
    app.dependency_overrides[get_current_user] = lambda: student_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {student_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


def test_session_service_does_not_import_classroom_or_structured_curriculum_models():
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "session_service.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned_modules = {
        "app.models.classroom",
        "app.services.classroom",
        "app.services.runtime",
        "app.models.curriculum.curriculum_zone",
        "app.models.curriculum.curriculum_cluster",
        "app.models.curriculum.curriculum_concept",
        "app.models.classroom.class_session_instance",
        "app.models.classroom.class_session_plan",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for banned in banned_modules:
                assert not node.module.startswith(banned), node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                for banned in banned_modules:
                    assert not alias.name.startswith(banned), alias.name
    runtime_imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.models.runtime")
    ]
    assert runtime_imports == ["app.models.runtime.runtime_curriculum_manifest"]


@pytest.mark.asyncio
async def test_personal_then_classroom_launch_coexistence(
    db,
    org,
    classroom_api_client,
    student_api_client,
    teacher_topic,
    student_user,
):
    """Personal session uses TeacherTopic keys; classroom launch uses manifest slice."""
    service = SessionService(SessionRepository(), TopicRepository())
    personal = await service.start_session(
        student_id=student_user.id,
        topic_id=teacher_topic.id,
        student_organization_id=org.id,
    )
    assert not isinstance(personal, dict)
    assert personal.key_concepts == teacher_topic.key_concepts

    tid = str(teacher_topic.id)
    seeded = await _seed_zone1_cluster_a(classroom_api_client, tid)
    instance_id = await _create_classroom_instance(
        classroom_api_client,
        teacher_topic=teacher_topic,
        seeded=seeded,
    )
    enroll = await classroom_api_client.post(
        f"/classroom/instances/{instance_id}/enrollments",
        json={"student_ids": [str(student_user.id)]},
    )
    assert enroll.status_code == 200, enroll.text

    blocked = await student_api_client.post(
        f"/student/classroom/instances/{instance_id}/launch",
        json={},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["type"] == "resume_prompt"

    await SessionRepository().end_session(personal.id)
    ended = await Session.get(personal.id)
    assert ended is not None
    await ended.delete()

    relaunch = await student_api_client.post(
        f"/student/classroom/instances/{instance_id}/launch",
        json={},
    )
    assert relaunch.status_code == 200, relaunch.text
    assert relaunch.json()["type"] == "session"

    session = await Session.get(relaunch.json()["session_id"])
    assert session is not None
    assert session.key_concepts == ["concept_1", "concept_2"]
    assert session.key_concepts != teacher_topic.key_concepts
    assert session.current_concept == "concept_1"
