"""Integration tests for classroom planning API (Phase 3A)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin
from app.main import app
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


async def _seed_teacher_curriculum(client, teacher_topic_id: str) -> dict:
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
    for name in ["Core Concept A"]:
        c = await client.post(
            "/curriculum/concepts",
            json={
                "topic_id": teacher_topic_id,
                "topic_source": "teacher",
                "curriculum_cluster_id": cluster_id,
                "display_name": name,
                "vtse_template": MINIMAL_VTSE_TEMPLATE,
            },
        )
        assert c.status_code == 201, c.text
    pub = await client.post(
        f"/topics/{teacher_topic_id}/curriculum/publish",
        params={"topic_source": "teacher"},
    )
    assert pub.status_code == 200, pub.text
    z1c = next(
        c
        for z in (
            await client.get(
                f"/topics/{teacher_topic_id}/curriculum",
                params={"topic_source": "teacher"},
            )
        ).json()["zones"]
        if z["zone_number"] == 1
        for c in z["clusters"]
    )
    return {
        "zone0_id": z0["id"],
        "zone1_id": z1["id"],
        "cluster1_id": z1c["id"],
    }


@pytest.mark.asyncio
async def test_classroom_plan_publish_and_instance(
    classroom_api_client, teacher_topic
):
    tid = str(teacher_topic.id)
    seeded = await _seed_teacher_curriculum(classroom_api_client, tid)

    create = await classroom_api_client.post(
        "/classroom/plans",
        json={
            "teacher_topic_id": tid,
            "class_id": teacher_topic.class_id,
            "subject_id": teacher_topic.subject_id,
            "sequence_number": 1,
            "title": "Session 1",
        },
    )
    assert create.status_code == 201, create.text
    plan_id = create.json()["id"]

    items = await classroom_api_client.put(
        f"/classroom/plans/{plan_id}/items",
        json={
            "items": [
                {
                    "sort_order": 0,
                    "item_type": "zone_coverage",
                    "curriculum_zone_id": seeded["zone0_id"],
                    "zone_number": 0,
                },
                {
                    "sort_order": 1,
                    "item_type": "cluster_coverage",
                    "curriculum_zone_id": seeded["zone1_id"],
                    "curriculum_cluster_id": seeded["cluster1_id"],
                },
            ]
        },
    )
    assert items.status_code == 200, items.text

    pub = await classroom_api_client.post(f"/classroom/plans/{plan_id}/publish")
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    inst = await classroom_api_client.post(
        "/classroom/instances",
        json={
            "class_session_plan_id": plan_id,
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "timezone": "UTC",
        },
    )
    assert inst.status_code == 201, inst.text
    instance_id = inst.json()["id"]

    enroll = await classroom_api_client.post(
        f"/classroom/instances/{instance_id}/enrollments",
        json={"student_ids": []},
    )
    assert enroll.status_code == 400
