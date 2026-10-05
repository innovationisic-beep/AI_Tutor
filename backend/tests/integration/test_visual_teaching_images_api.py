"""Visual Teaching image upload/serve API: MIME, probe, tenancy, replace, cleanup."""

from __future__ import annotations

import hashlib
import struct
import zlib
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.core.security import create_access_token, hash_password
from app.main import app
from app.services.storage.visual_teaching_storage import (
    MAX_IMAGE_BYTES,
    LocalVisualTeachingStorage,
    set_visual_teaching_storage,
)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_png(width: int = 8, height: int = 6) -> bytes:
    raw = b"".join(b"\x00" + bytes([200, 40, 40]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def make_jpeg(width: int = 8, height: int = 6) -> bytes:
    """Minimal baseline JPEG with a SOF0 that carries width/height."""
    sof = (
        b"\xff\xc0"
        + struct.pack(">H", 8 + 3 * 3)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    # Minimal tables so decoders don't choke; probe only needs SOF0.
    return b"\xff\xd8" + sof + b"\xff\xd9"


def make_webp(width: int = 8, height: int = 6) -> bytes:
    payload = bytearray(10)
    payload[4:7] = (width - 1).to_bytes(3, "little")
    payload[7:10] = (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + bytes(payload)
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


PNG = make_png(12, 9)
JPEG = make_jpeg(10, 7)
WEBP = make_webp(11, 5)

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


@pytest.fixture()
def storage(tmp_path):
    store = LocalVisualTeachingStorage(tmp_path / "visual_teaching")
    set_visual_teaching_storage(store)
    try:
        yield store
    finally:
        set_visual_teaching_storage(None)


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


async def _upload(
    client,
    concept_id: str,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    replace_asset_key: str | None = None,
    topic_source: str = "catalog",
):
    params: dict = {"topic_source": topic_source}
    if replace_asset_key:
        params["replace_asset_key"] = replace_asset_key
    return await client.post(
        f"/curriculum/concepts/{concept_id}/visual-teaching/images",
        params=params,
        files={"file": (filename, content, content_type)},
    )


async def _attach_image(
    client,
    concept_id: str,
    uploaded: dict,
    *,
    annotations_status: str = "confirmed",
    regions: list | None = None,
    teaching_sequence: list | None = None,
    topic_source: str = "catalog",
    extra_images: list | None = None,
):
    images = [
        {
            "id": uploaded["id"],
            "asset_key": uploaded["asset_key"],
            "storage_key": uploaded["storage_key"],
            "mime_type": uploaded["mime_type"],
            "sort_order": 0,
            "title": uploaded["asset_key"],
            "teaching_purpose": "Show the pore.",
            "natural_width": uploaded["natural_width"],
            "natural_height": uploaded["natural_height"],
            "content_hash": uploaded["content_hash"],
            "annotations_status": annotations_status,
            "regions": regions
            or [
                {
                    "region_id": "pore",
                    "label": "Pore",
                    "teaching_purpose": "Opening",
                    "sort_order": 0,
                    "shape": "rect",
                    "geometry": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    "focus_point": {"x": 0.25, "y": 0.35},
                }
            ],
            "anchors": [],
            "connections": [],
        }
    ]
    if extra_images:
        images.extend(extra_images)
    body: dict = {
        "topic_source": topic_source,
        "visual_teaching": {"images": images},
    }
    if teaching_sequence is not None:
        body["teaching_sequence"] = teaching_sequence
    return await client.put(
        f"/curriculum/concepts/{concept_id}",
        params={"topic_source": topic_source},
        json=body,
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_accepts_jpeg_png_webp(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))

    for content, filename, mime, w, h in (
        (JPEG, "leaf.jpg", "image/jpeg", 10, 7),
        (PNG, "leaf.png", "image/png", 12, 9),
        (WEBP, "leaf.webp", "image/webp", 11, 5),
    ):
        res = await _upload(
            api_client,
            concept_id,
            content=content,
            filename=filename,
            content_type=mime,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["mime_type"] == mime
        assert body["natural_width"] == w
        assert body["natural_height"] == h
        assert body["content_hash"] == hashlib.sha256(content).hexdigest()
        assert body["annotations_status"] == "confirmed"
        assert await storage.exists(body["storage_key"]) is True


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_mime(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    res = await _upload(
        api_client,
        concept_id,
        content=b"%PDF-1.4",
        filename="notes.pdf",
        content_type="application/pdf",
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "UNSUPPORTED_IMAGE_TYPE"
    assert not list(storage.root.glob("*")) if storage.root.exists() else True


@pytest.mark.asyncio
async def test_upload_rejects_oversize(api_client, catalog_topic, storage):
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
async def test_upload_rejects_corrupt_image(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    res = await _upload(
        api_client,
        concept_id,
        content=b"\x89PNG\r\n\x1a\nnot-a-real-png",
        filename="broken.png",
        content_type="image/png",
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_IMAGE"
    assert not list(storage.root.glob("*")) if storage.root.exists() else True


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

    # GET before attach → 404 (binary committed, not durable on concept yet).
    missing = await api_client.get(
        f"/curriculum/concepts/{concept_id}/visual-teaching/images/stomata_surface"
    )
    assert missing.status_code == 404

    attach = await _attach_image(
        api_client,
        concept_id,
        visual,
        teaching_sequence=["vtse", "visual_teaching"],
    )
    assert attach.status_code == 200, attach.text
    saved = attach.json()["visual_teaching"]["images"][0]
    assert saved["asset_key"] == "stomata_surface"
    assert saved["content_hash"] == hashlib.sha256(PNG).hexdigest()
    assert saved["natural_width"] == 12
    assert saved["natural_height"] == 9

    served = await api_client.get(
        f"/curriculum/concepts/{concept_id}/visual-teaching/images/stomata_surface"
    )
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_duplicate_filenames_get_distinct_asset_keys(
    api_client, catalog_topic, storage
):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    first = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert first.status_code == 201, first.text
    attach = await _attach_image(api_client, concept_id, first.json())
    assert attach.status_code == 200, attach.text
    second = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert second.status_code == 201, second.text
    assert first.json()["asset_key"] == "leaf"
    assert second.json()["asset_key"] == "leaf-2"
    assert first.json()["storage_key"] != second.json()["storage_key"]


# ---------------------------------------------------------------------------
# Security / tenancy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_get_denied(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    up = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert (await _attach_image(api_client, concept_id, up.json())).status_code == 200

    app.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as anon:
        res = await anon.get(
            f"/curriculum/concepts/{concept_id}/visual-teaching/images/leaf"
        )
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_raw_storage_key_cannot_be_used_as_lookup(
    api_client, catalog_topic, storage
):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    up = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert (await _attach_image(api_client, concept_id, up.json())).status_code == 200
    storage_key = up.json()["storage_key"]
    res = await api_client.get(
        f"/curriculum/concepts/{concept_id}/visual-teaching/images/{storage_key}"
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_teacher_denied_for_teacher_owned_asset(
    db, org, teacher_user, teacher_token, storage
):
    from app.models.curriculum.curriculum_cluster import CurriculumCluster
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone
    from app.models.identification.users import User
    from app.models.organization import Organization
    from app.models.teacher_topic import TeacherTopic

    other_org = Organization(
        name="Other School",
        organization_type="institution",
        status="active",
        max_students=100,
        max_teachers=20,
    )
    await other_org.insert()
    other_teacher = User(
        organization_id=other_org.id,
        email="other-teacher@otherschool.com",
        password_hash=hash_password("OtherPass123!"),
        role="teacher",
        status="active",
    )
    await other_teacher.insert()
    other_token = create_access_token({"user_id": str(other_teacher.id)})

    teacher_topic = TeacherTopic(
        organization_id=org.id,
        teacher_id=teacher_user.id,
        class_id="c1",
        subject_id="s1",
        topic_name="VT Tenancy",
    )
    await teacher_topic.insert()

    key = await storage.save(data=PNG, content_type="image/png", key_hint="leaf")
    zone = await CurriculumZone(
        organization_id=org.id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        allows_vtse=True,
        status="draft",
    ).insert()
    cluster = await CurriculumCluster(
        organization_id=org.id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone.id,
        cluster_number=1,
        title="Cluster",
        status="draft",
    ).insert()
    concept = await CurriculumConcept(
        organization_id=org.id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone.id,
        curriculum_cluster_id=cluster.id,
        slug="guard-cells",
        display_name="Guard Cells",
        canonical_runtime_key="guard_cells",
        visual_teaching={
            "images": [
                {
                    "id": "img1",
                    "asset_key": "leaf",
                    "storage_key": key,
                    "mime_type": "image/png",
                    "sort_order": 0,
                    "teaching_purpose": "Show pore",
                    "natural_width": 12,
                    "natural_height": 9,
                    "content_hash": hashlib.sha256(PNG).hexdigest(),
                    "annotations_status": "confirmed",
                    "regions": [],
                    "anchors": [],
                    "connections": [],
                }
            ]
        },
        status="draft",
    ).insert()

    # Owning org teacher can stream.
    app.dependency_overrides[get_current_user] = lambda: teacher_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {teacher_token}"},
    ) as client:
        ok = await client.get(
            f"/curriculum/concepts/{concept.id}/visual-teaching/images/leaf"
        )
    assert ok.status_code == 200
    assert ok.content == PNG

    # Cross-tenant teacher denied (404, not leak).
    app.dependency_overrides[get_current_user] = lambda: other_teacher
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as client:
        denied = await client.get(
            f"/curriculum/concepts/{concept.id}/visual-teaching/images/leaf"
        )
    assert denied.status_code == 404
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Replace / stale / publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_forces_stale_new_key_and_blocks_publish(
    api_client, catalog_topic, storage
):
    from unittest.mock import AsyncMock, MagicMock

    from app.services.curriculum.curriculum_validation_service import (
        CurriculumValidationService,
    )

    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    first = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert first.status_code == 201, first.text
    old_key = first.json()["storage_key"]
    attach = await _attach_image(api_client, concept_id, first.json())
    assert attach.status_code == 200, attach.text
    assert attach.json()["visual_teaching"]["images"][0]["annotations_status"] == (
        "confirmed"
    )

    replacement = make_png(16, 12)
    replaced = await _upload(
        api_client,
        concept_id,
        content=replacement,
        filename="leaf.png",
        content_type="image/png",
        replace_asset_key="leaf",
    )
    assert replaced.status_code == 201, replaced.text
    body = replaced.json()
    assert body["asset_key"] == "leaf"
    assert body["storage_key"] != old_key
    assert body["annotations_status"] == "stale"
    assert body["natural_width"] == 16
    assert body["natural_height"] == 12

    # Client cannot force confirmed on replace save.
    save = await _attach_image(
        api_client,
        concept_id,
        body,
        annotations_status="confirmed",
        teaching_sequence=["vtse", "visual_teaching"],
    )
    assert save.status_code == 200, save.text
    saved = save.json()["visual_teaching"]["images"][0]
    assert saved["annotations_status"] == "stale"
    assert saved["storage_key"] == body["storage_key"]
    assert await storage.exists(body["storage_key"]) is True
    # Old binary cleaned after successful metadata commit.
    assert await storage.exists(old_key) is False

    # Publish blocked while stale.
    tree = {
        "zones": [
            {
                "zone_number": 1,
                "clusters": [
                    {
                        "cluster_number": 1,
                        "title": "Cluster A",
                        "concepts": [
                            {
                                "slug": "stomata",
                                "display_name": "Stomata",
                                "teaching_sequence": ["vtse", "visual_teaching"],
                                "vtse_template": VTSE,
                                "visual_teaching": {
                                    "images": [saved],
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    tree_svc = MagicMock()
    tree_svc.get_tree = AsyncMock(return_value=tree)
    result = await CurriculumValidationService(tree_service=tree_svc).validate(
        MagicMock()
    )
    assert result.ready_to_publish is False
    assert any(e.code == "VISUAL_TEACHING_STALE_ANNOTATIONS" for e in result.errors)

    # Explicit reconfirm (same storage_key) succeeds.
    reconfirm = await _attach_image(
        api_client,
        concept_id,
        {
            **body,
            "storage_key": saved["storage_key"],
            "natural_width": saved["natural_width"],
            "natural_height": saved["natural_height"],
            "content_hash": saved["content_hash"],
        },
        annotations_status="confirmed",
        teaching_sequence=["vtse", "visual_teaching"],
    )
    assert reconfirm.status_code == 200, reconfirm.text
    assert (
        reconfirm.json()["visual_teaching"]["images"][0]["annotations_status"]
        == "confirmed"
    )


# ---------------------------------------------------------------------------
# Delete / cleanup / GC assumptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_image_removes_storage_object(api_client, catalog_topic, storage):
    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    up = await _upload(
        api_client, concept_id, content=PNG, filename="leaf.png", content_type="image/png"
    )
    assert (await _attach_image(api_client, concept_id, up.json())).status_code == 200
    key = up.json()["storage_key"]
    assert await storage.exists(key) is True

    cleared = await api_client.put(
        f"/curriculum/concepts/{concept_id}",
        params={"topic_source": "catalog"},
        json={"topic_source": "catalog", "visual_teaching": {"images": []}},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json().get("visual_teaching") in (None, {"images": []}) or (
        cleared.json().get("visual_teaching", {}).get("images") == []
    )
    assert await storage.exists(key) is False


@pytest.mark.asyncio
async def test_upload_without_attach_is_unreferenced_orphan_for_gc(
    api_client, catalog_topic, storage
):
    """Upload commits bytes immediately; GC sweeper assumes unreferenced keys are orphans."""
    from scripts.visual_teaching_gc import referenced_storage_keys

    concept_id = await _seed_concept(api_client, str(catalog_topic.id))
    up = await _upload(
        api_client, concept_id, content=PNG, filename="orphan.png", content_type="image/png"
    )
    assert up.status_code == 201, up.text
    key = up.json()["storage_key"]
    assert await storage.exists(key) is True

    # Concept never attached the key → GET 404 and not in referenced set.
    missing = await api_client.get(
        f"/curriculum/concepts/{concept_id}/visual-teaching/images/orphan"
    )
    assert missing.status_code == 404

    from motor.motor_asyncio import AsyncIOMotorClient
    from app.core.config import settings

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        db = client.get_database("test_db")
        refs = await referenced_storage_keys(db)
    finally:
        client.close()
    assert key not in refs
