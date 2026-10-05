"""Integration tests for structured curriculum APIs (Phase 1)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin
from app.main import app


@pytest.fixture
async def api_client(db, admin_user, admin_token):
    app.dependency_overrides[get_current_teacher_or_admin] = lambda: admin_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def teacher_api_client(db, teacher_user, teacher_token):
    app.dependency_overrides[get_current_teacher_or_admin] = lambda: teacher_user
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {teacher_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_minimal_curriculum(client, topic_id: str, topic_source: str) -> dict:
  z0 = await client.post(
      "/curriculum/zones",
      json={
          "topic_id": topic_id,
          "topic_source": topic_source,
          "zone_number": 0,
          "title": "Curiosity",
      },
  )
  assert z0.status_code == 201, z0.text
  z1 = await client.post(
      "/curriculum/zones",
      json={
          "topic_id": topic_id,
          "topic_source": topic_source,
          "zone_number": 1,
          "title": "Core Teaching",
      },
  )
  assert z1.status_code == 201, z1.text
  zone1_id = z1.json()["id"]
  cl = await client.post(
      "/curriculum/clusters",
      json={
          "topic_id": topic_id,
          "topic_source": topic_source,
          "curriculum_zone_id": zone1_id,
          "title": "Cluster 1",
          "cluster_number": 1,
      },
  )
  assert cl.status_code == 201, cl.text
  cluster_id = cl.json()["id"]
  _vtse = {
      "strategy_id": "hierarchy_concept_intro",
      "version": 1,
      "payload": {
          "steps": [
              {"label": "Point A", "summary": "First teaching point"},
              {"label": "Point B", "summary": "Second teaching point"},
              {"label": "Point C", "summary": "Third teaching point"},
          ]
      },
  }
  c1 = await client.post(
      "/curriculum/concepts",
      json={
          "topic_id": topic_id,
          "topic_source": topic_source,
          "curriculum_cluster_id": cluster_id,
          "display_name": "Concept A",
          "vtse_template": _vtse,
      },
  )
  assert c1.status_code == 201, c1.text
  c2 = await client.post(
      "/curriculum/concepts",
      json={
          "topic_id": topic_id,
          "topic_source": topic_source,
          "curriculum_cluster_id": cluster_id,
          "display_name": "Concept B",
          "vtse_template": _vtse,
      },
  )
  assert c2.status_code == 201, c2.text
  return {
      "zone1_id": zone1_id,
      "cluster_id": cluster_id,
      "concept_a_id": c1.json()["id"],
      "concept_a_key": c1.json()["canonical_runtime_key"],
  }


@pytest.mark.asyncio
async def test_catalog_curriculum_tree_and_publish(api_client, catalog_topic):
    tid = str(catalog_topic.id)
    await _seed_minimal_curriculum(api_client, tid, "catalog")

    tree = await api_client.get(
        f"/topics/{tid}/curriculum",
        params={"topic_source": "catalog"},
    )
    assert tree.status_code == 200
    data = tree.json()
    assert data["topic_id"] == tid
    assert data["curriculum_schema_version"] == "v2"
    assert len(data["zones"]) == 2

    validation = await api_client.get(
        f"/topics/{tid}/curriculum/validate",
        params={"topic_source": "catalog"},
    )
    assert validation.status_code == 200
    assert validation.json()["ready_to_publish"] is True

    publish = await api_client.post(
        f"/topics/{tid}/curriculum/publish",
        params={"topic_source": "catalog"},
    )
    assert publish.status_code == 200
    body = publish.json()
    assert body["curriculum_revision"] == 1
    assert body["curriculum_schema_version"] == "v2"
    assert "curriculum_published_at" in body

    from app.models.curriculum.topics import Topic

    refreshed = await Topic.get(catalog_topic.id)
    assert refreshed is not None
    assert refreshed.curriculum_schema_version == "v2"
    assert refreshed.curriculum_revision == 1
    assert refreshed.curriculum_published_at is not None


@pytest.mark.asyncio
async def test_teacher_topic_curriculum(teacher_api_client, teacher_topic):
    tid = str(teacher_topic.id)
    await _seed_minimal_curriculum(teacher_api_client, tid, "teacher")

    tree = await teacher_api_client.get(
        f"/topics/{tid}/curriculum",
        params={"topic_source": "teacher"},
    )
    assert tree.status_code == 200
    assert len(tree.json()["zones"]) >= 2


@pytest.mark.asyncio
async def test_validate_fails_without_zone_1(api_client, catalog_topic):
    tid = str(catalog_topic.id)
    await api_client.post(
        "/curriculum/zones",
        json={
            "topic_id": tid,
            "topic_source": "catalog",
            "zone_number": 0,
            "title": "Curiosity only",
        },
    )
    validation = await api_client.get(
        f"/topics/{tid}/curriculum/validate",
        params={"topic_source": "catalog"},
    )
    assert validation.status_code == 200
    assert validation.json()["ready_to_publish"] is False
    codes = [e["code"] for e in validation.json()["errors"]]
    assert "MISSING_CURRICULUM_ZONE_1" in codes


@pytest.mark.asyncio
async def test_system_zone_cannot_delete(api_client, catalog_topic):
    tid = str(catalog_topic.id)
    z0 = await api_client.post(
        "/curriculum/zones",
        json={
            "topic_id": tid,
            "topic_source": "catalog",
            "zone_number": 0,
            "title": "Curiosity",
        },
    )
    zone_id = z0.json()["id"]
    res = await api_client.delete(
        f"/curriculum/zones/{zone_id}",
        params={"topic_source": "catalog"},
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_concept_usage_questions_only_ignores_notes(api_client, catalog_topic):
    tid = str(catalog_topic.id)
    seeded = await _seed_minimal_curriculum(api_client, tid, "catalog")
    concept_id = seeded["concept_a_id"]
    canonical = seeded["concept_a_key"]

    usage_before = await api_client.get(
        f"/curriculum/concepts/{concept_id}/usage",
        params={"topic_source": "catalog"},
    )
    assert usage_before.status_code == 200
    assert usage_before.json()["note_count"] == 0
    assert usage_before.json()["question_count"] == 0

    # Creating a TopicNote must not surface in concept usage (notes retired from authoring).
    note = await api_client.post(
        "/admin/topic-note",
        json={
            "topic_id": tid,
            "concept_id": concept_id,
            "structured": True,
            "content_markdown": "Structured note body",
            "note_type": "detailed",
            "difficulty_level": "medium",
        },
    )
    assert note.status_code == 200, note.text

    usage_after = await api_client.get(
        f"/curriculum/concepts/{concept_id}/usage",
        params={"topic_source": "catalog"},
    )
    assert usage_after.status_code == 200
    body = usage_after.json()
    assert body["note_count"] == 0
    assert body["notes"] == []
    assert body["canonical_runtime_key"] == canonical
    assert body["question_count"] == 0
