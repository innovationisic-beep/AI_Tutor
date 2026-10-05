"""Integration tests for classroom session launch (Phase 3B.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.main import app
from app.models.learning.sessions import Session
from tests.helpers import MINIMAL_VTSE_TEMPLATE


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


async def _seed_zone1_cluster_a(client, teacher_topic_id: str) -> dict:
    for zn, title in [(0, "Curiosity"), (1, "Core Teaching")]:
        z = await client.post(
            "/curriculum/zones",
            json={
                "topic_id": teacher_topic_id,
                "topic_source": "teacher",
                "zone_number": zn,
                "title": title,
            },
        )
        assert z.status_code == 201, z.text
    tree = await client.get(
        f"/topics/{teacher_topic_id}/curriculum",
        params={"topic_source": "teacher"},
    )
    assert tree.status_code == 200
    zones = tree.json()["zones"]
    z0 = next(z for z in zones if z["zone_number"] == 0)
    z1 = next(z for z in zones if z["zone_number"] == 1)
    cl = await client.post(
        "/curriculum/clusters",
        json={
            "topic_id": teacher_topic_id,
            "topic_source": "teacher",
            "curriculum_zone_id": z1["id"],
            "title": "Cluster A",
            "cluster_number": 1,
        },
    )
    assert cl.status_code == 201, cl.text
    cluster_id = cl.json()["id"]
    concept_keys: list[str] = []
    for name, explicit_key in [
        ("Concept 1", "concept_1"),
        ("Concept 2", "concept_2"),
    ]:
        c = await client.post(
            "/curriculum/concepts",
            json={
                "topic_id": teacher_topic_id,
                "topic_source": "teacher",
                "curriculum_cluster_id": cluster_id,
                "display_name": name,
                "canonical_runtime_key": explicit_key,
                "vtse_template": MINIMAL_VTSE_TEMPLATE,
            },
        )
        assert c.status_code == 201, c.text
        concept_keys.append(c.json()["canonical_runtime_key"])
    pub = await client.post(
        f"/topics/{teacher_topic_id}/curriculum/publish",
        params={"topic_source": "teacher"},
    )
    assert pub.status_code == 200, pub.text
    return {
        "zone0_id": z0["id"],
        "zone1_id": z1["id"],
        "cluster1_id": cluster_id,
        "concept_keys": concept_keys,
    }


async def _create_classroom_instance(
    client,
    *,
    teacher_topic,
    seeded: dict,
) -> str:
    tid = str(teacher_topic.id)

    zone0_plan = await client.post(
        "/classroom/plans",
        json={
            "teacher_topic_id": tid,
            "class_id": teacher_topic.class_id,
            "subject_id": teacher_topic.subject_id,
            "sequence_number": 1,
            "title": "Session 0",
        },
    )
    assert zone0_plan.status_code == 201, zone0_plan.text
    zone0_plan_id = zone0_plan.json()["id"]
    zone0_items = await client.put(
        f"/classroom/plans/{zone0_plan_id}/items",
        json={
            "items": [
                {
                    "sort_order": 0,
                    "item_type": "zone_coverage",
                    "curriculum_zone_id": seeded["zone0_id"],
                    "zone_number": 0,
                }
            ]
        },
    )
    assert zone0_items.status_code == 200, zone0_items.text
    zone0_pub = await client.post(f"/classroom/plans/{zone0_plan_id}/publish")
    assert zone0_pub.status_code == 200, zone0_pub.text

    create = await client.post(
        "/classroom/plans",
        json={
            "teacher_topic_id": tid,
            "class_id": teacher_topic.class_id,
            "subject_id": teacher_topic.subject_id,
            "sequence_number": 2,
            "title": "Session 1",
        },
    )
    assert create.status_code == 201, create.text
    plan_id = create.json()["id"]
    items = await client.put(
        f"/classroom/plans/{plan_id}/items",
        json={
            "items": [
                {
                    "sort_order": 0,
                    "item_type": "cluster_coverage",
                    "curriculum_zone_id": seeded["zone1_id"],
                    "curriculum_cluster_id": seeded["cluster1_id"],
                }
            ]
        },
    )
    assert items.status_code == 200, items.text
    pub = await client.post(f"/classroom/plans/{plan_id}/publish")
    assert pub.status_code == 200, pub.text
    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    inst = await client.post(
        "/classroom/instances",
        json={
            "class_session_plan_id": plan_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "timezone": "UTC",
        },
    )
    assert inst.status_code == 201, inst.text
    return inst.json()["id"]


@pytest.mark.asyncio
async def test_classroom_launch_sets_session_keys(
    classroom_api_client,
    student_api_client,
    teacher_topic,
    student_user,
):
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

    launch = await student_api_client.post(
        f"/student/classroom/instances/{instance_id}/launch",
        json={},
    )
    assert launch.status_code == 200, launch.text
    body = launch.json()
    assert body["type"] == "session"
    assert body["manifest_summary"]["key_count"] == 2
    assert body["manifest_summary"]["first_concept"] == "concept_1"
    assert body["manifest_summary"]["launch_context"]["launch_kind"] == "classroom"

    session = await Session.get(body["session_id"])
    assert session is not None
    assert session.key_concepts == ["concept_1", "concept_2"]
    assert session.current_concept == "concept_1"
    assert session.concept_clusters == [["concept_1", "concept_2"]]
