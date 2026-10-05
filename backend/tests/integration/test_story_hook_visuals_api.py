"""Story Hook visual upload/serve API: validation, tenancy, opaque keys."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.main import app
from app.services.storage.story_hook_storage import (
    MAX_IMAGE_BYTES,
    LocalStoryHookStorage,
    set_story_hook_storage,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 64


@pytest.fixture()
def storage(tmp_path):
    store = LocalStoryHookStorage(tmp_path / "story_hook")
    set_story_hook_storage(store)
    try:
        yield store
    finally:
        set_story_hook_storage(None)


@pytest.fixture
async def api_client(db, admin_user, admin_token):
    app.dependency_overrides[get_current_teacher_or_admin] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


VTSE = {
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


async def _seed_concept(client, topic_id: str) -> str:
    zone = await client.post(
        "/curriculum/zones",
        json={
            "topic_id": topic_id,
            "topic_source": "catalog",
            "zone_number": 1,
            "title": "Core Teaching",
        },
    )
    assert zone.status_code == 201, zone.text
    cluster = await client.post(
        "/curriculum/clusters",
        json={
            "topic_id": topic_id,
            "topic_source": "catalog",
            "curriculum_zone_id": zone.json()["id"],
            "title": "Leaf structure",
            "cluster_number": 1,
        },
    )
    assert cluster.status_code == 201, cluster.text
    concept = await client.post(
        "/curriculum/concepts",
        json={
            "topic_id": topic_id,
            "topic_source": "catalog",
            "curriculum_cluster_id": cluster.json()["id"],
            "display_name": "Stomata",
            "vtse_template": VTSE,
        },
    )
    assert concept.status_code == 201, concept.text
    return concept.json()["id"]


async def _upload(client, concept_id: str, *, content, filename, content_type):
    return await client.post(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals",
        params={"topic_source": "catalog"},
        files={"file": (filename, content, content_type)},
    )


@pytest.mark.asyncio
async def test_upload_then_attach_then_stream(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    uploaded = await _upload(
        api_client,
        concept_id,
        content=PNG,
        filename="Stomata Surface.png",
        content_type="image/png",
    )
    assert uploaded.status_code == 201, uploaded.text
    visual = uploaded.json()
    assert visual["asset_key"] == "stomata_surface"
    assert visual["mime_type"] == "image/png"
    assert visual["size_bytes"] == len(PNG)
    # Mongo holds a key, never the bytes.
    assert await storage.exists(visual["storage_key"]) is True

    attach = await api_client.put(
        f"/curriculum/concepts/{concept_id}",
        params={"topic_source": "catalog"},
        json={
            "topic_source": "catalog",
            "story_hook": {
                "title": "Leaf doors",
                "body": "A leaf breathing through tiny doors.",
                "teacher_intent": "Emphasise guard cell control.",
                "visuals": [
                    {
                        "asset_key": visual["asset_key"],
                        "storage_key": visual["storage_key"],
                        "description": "Microscope view of pores.",
                        "teaching_purpose": "Show how many pores there are.",
                        "mime_type": visual["mime_type"],
                    }
                ],
            },
            "teaching_sequence": ["story_hook", "vtse"],
        },
    )
    assert attach.status_code == 200, attach.text
    saved = attach.json()["story_hook"]["visuals"][0]
    assert saved["asset_key"] == "stomata_surface"
    assert saved["teaching_purpose"] == "Show how many pores there are."

    served = await api_client.get(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals/stomata_surface"
    )
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_non_image_uploads_are_rejected(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    res = await _upload(
        api_client,
        concept_id,
        content=b"%PDF-1.4 fake",
        filename="notes.pdf",
        content_type="application/pdf",
    )

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "UNSUPPORTED_IMAGE_TYPE"
    assert not list(storage.root.glob("*")) if storage.root.exists() else True


@pytest.mark.asyncio
async def test_oversize_uploads_are_rejected(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    res = await _upload(
        api_client,
        concept_id,
        content=b"x" * (MAX_IMAGE_BYTES + 1),
        filename="huge.png",
        content_type="image/png",
    )

    assert res.status_code == 413
    assert res.json()["detail"]["code"] == "IMAGE_TOO_LARGE"


@pytest.mark.asyncio
async def test_empty_uploads_are_rejected(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    res = await _upload(
        api_client,
        concept_id,
        content=b"",
        filename="empty.png",
        content_type="image/png",
    )

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "EMPTY_IMAGE"


@pytest.mark.asyncio
async def test_duplicate_filenames_get_distinct_asset_keys(
    api_client, catalog_topic, storage
):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    first = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    attach = await api_client.put(
        f"/curriculum/concepts/{concept_id}",
        params={"topic_source": "catalog"},
        json={
            "topic_source": "catalog",
            "story_hook": {
                "body": "seed",
                "visuals": [
                    {
                        "asset_key": first.json()["asset_key"],
                        "storage_key": first.json()["storage_key"],
                        "mime_type": "image/png",
                    }
                ],
            },
        },
    )
    assert attach.status_code == 200, attach.text
    second = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )

    assert first.json()["asset_key"] == "leaf"
    assert second.json()["asset_key"] == "leaf-2"
    assert first.json()["storage_key"] != second.json()["storage_key"]


@pytest.mark.asyncio
async def test_unknown_asset_key_is_not_found(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    res = await api_client.get(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals/nope"
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_before_concept_attach_is_404(api_client, catalog_topic, storage):
    """Upload stores bytes immediately; GET requires visuals[] on the concept."""
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    uploaded = await _upload(
        api_client,
        concept_id,
        content=PNG,
        filename="living thing.webp",
        content_type="image/webp",
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["asset_key"] == "living_thing"

    missing = await api_client.get(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals/living_thing"
    )
    assert missing.status_code == 404

    attach = await api_client.put(
        f"/curriculum/concepts/{concept_id}",
        params={"topic_source": "catalog"},
        json={
            "topic_source": "catalog",
            "story_hook": {
                "title": "Living things",
                "body": "What makes something alive?",
                "visuals": [
                    {
                        "asset_key": "living_thing",
                        "storage_key": uploaded.json()["storage_key"],
                        "mime_type": "image/webp",
                    }
                ],
            },
            "teaching_sequence": ["story_hook", "vtse"],
        },
    )
    assert attach.status_code == 200, attach.text

    ok = await api_client.get(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals/living_thing"
    )
    assert ok.status_code == 200
    assert ok.content == PNG


@pytest.mark.asyncio
async def test_client_cannot_ask_for_a_raw_storage_path(
    api_client, catalog_topic, storage
):
    """The media route keys off asset_key only — traversal has no surface."""
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    uploaded = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    storage_key = uploaded.json()["storage_key"]

    res = await api_client.get(
        f"/curriculum/concepts/{concept_id}/story-hook/visuals/{storage_key}"
    )

    assert res.status_code == 404
