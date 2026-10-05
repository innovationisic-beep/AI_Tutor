"""Admin → Teacher Visual Teaching clone integration coverage."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.services.curriculum.curriculum_clone_service import (
    CurriculumCloneService,
    clone_structured_curriculum,
)
from app.services.storage.visual_teaching_storage import (
    LocalVisualTeachingStorage,
    StorageError,
    set_visual_teaching_storage,
)


PNG_A = b"\x89PNG\r\n\x1a\n" + b"leaf-surface-bytes-aaa"
PNG_B = b"\x89PNG\r\n\x1a\n" + b"leaf-cross-section-bbb"


@pytest.fixture()
def vt_storage(tmp_path):
    storage = LocalVisualTeachingStorage(tmp_path / "visual_teaching")
    set_visual_teaching_storage(storage)
    try:
        yield storage
    finally:
        set_visual_teaching_storage(None)


async def _read_all(storage, storage_key: str) -> bytes:
    chunks: list[bytes] = []
    async for chunk in storage.open_read(storage_key):
        chunks.append(chunk)
    return b"".join(chunks)


def _image_payload(
    *,
    image_id: str,
    asset_key: str,
    storage_key: str,
    sort_order: int,
    teaching_purpose: str,
    annotations_status: str,
    region_id: str,
    geometry: dict,
    focus_point: dict,
    anchor_a: str,
    anchor_b: str,
    connection_id: str,
) -> dict:
    return {
        "id": image_id,
        "asset_key": asset_key,
        "storage_key": storage_key,
        "mime_type": "image/png",
        "sort_order": sort_order,
        "title": asset_key,
        "teaching_purpose": teaching_purpose,
        "natural_width": 800,
        "natural_height": 600,
        "annotations_status": annotations_status,
        "regions": [
            {
                "region_id": region_id,
                "label": f"Label {region_id}",
                "teaching_purpose": f"Purpose {region_id}",
                "sort_order": 0,
                "shape": "rect",
                "geometry": geometry,
                "focus_point": focus_point,
            }
        ],
        "anchors": [
            {
                "anchor_id": anchor_a,
                "label": "A",
                "point": {"x": 0.2, "y": 0.3},
            },
            {
                "anchor_id": anchor_b,
                "label": "B",
                "point": {"x": 0.7, "y": 0.6},
            },
        ],
        "connections": [
            {
                "connection_id": connection_id,
                "from_anchor": anchor_a,
                "to_anchor": anchor_b,
                "label": "flow",
                "kind": "flow",
            }
        ],
    }


async def _build_admin_vt_tree(
    *,
    visual_teaching: dict,
) -> tuple[Topic, object]:
    from app.models.curriculum.curriculum_cluster import CurriculumCluster
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone

    catalog = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Visual Teaching Clone",
        topic_slug="visual-teaching-clone",
        topic_description="VT clone coverage",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        curriculum_revision=1,
        curriculum_published_at=datetime.now(timezone.utc),
        supports_class_sessions=True,
    )
    await catalog.insert()
    zone = await CurriculumZone(
        organization_id=None,
        topic_id=catalog.id,
        topic_source="catalog",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        allows_vtse=True,
        status="published",
    ).insert()
    cluster = await CurriculumCluster(
        organization_id=None,
        topic_id=catalog.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        cluster_number=1,
        title="Cluster A",
        status="published",
    ).insert()
    concept = await CurriculumConcept(
        organization_id=None,
        topic_id=catalog.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        curriculum_cluster_id=cluster.id,
        slug="guard-cells",
        display_name="Guard Cells",
        canonical_runtime_key="guard_cells",
        visual_teaching=visual_teaching,
        teaching_sequence=["story_hook", "vtse", "visual_teaching"],
        status="published",
    ).insert()
    return catalog, concept


async def _teacher_topic(org, teacher_user, catalog) -> TeacherTopic:
    teacher = TeacherTopic(
        organization_id=org.id,
        teacher_id=teacher_user.id,
        class_id="c1",
        subject_id="s1",
        topic_name=catalog.topic_name,
        curriculum_topic_id=catalog.id,
    )
    await teacher.insert()
    return teacher


@pytest.mark.asyncio
async def test_admin_to_teacher_visual_teaching_clone_preserves_semantics(
    db,
    org,
    teacher_user,
    vt_storage,
):
    """Teacher copy owns new binaries; semantic IDs and geometry stay exact."""
    from app.models.curriculum.curriculum_concept import CurriculumConcept

    key_a = await vt_storage.save(
        data=PNG_A, content_type="image/png", key_hint="stomata_surface"
    )
    key_b = await vt_storage.save(
        data=PNG_B, content_type="image/png", key_hint="stomata_cross"
    )
    source_pkg = {
        "images": [
            _image_payload(
                image_id="img_admin_a",
                asset_key="stomata_surface",
                storage_key=key_a,
                sort_order=0,
                teaching_purpose="Show the pore opening.",
                annotations_status="confirmed",
                region_id="pore_opening",
                geometry={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                focus_point={"x": 0.25, "y": 0.35},
                anchor_a="anchor_left",
                anchor_b="anchor_right",
                connection_id="conn_flow_1",
            ),
            _image_payload(
                image_id="img_admin_b",
                asset_key="stomata_cross",
                storage_key=key_b,
                sort_order=1,
                teaching_purpose="Show guard cell turgor.",
                annotations_status="stale",
                region_id="guard_cell",
                geometry={"x": 0.15, "y": 0.25, "w": 0.35, "h": 0.45},
                focus_point={"x": 0.4, "y": 0.5},
                anchor_a="anchor_top",
                anchor_b="anchor_bottom",
                connection_id="conn_compare_1",
            ),
        ]
    }
    catalog, source_concept = await _build_admin_vt_tree(visual_teaching=source_pkg)
    teacher = await _teacher_topic(org, teacher_user, catalog)

    result = await clone_structured_curriculum(
        source_topic_id=catalog.id,
        source_topic_source="catalog",
        source_organization_id=None,
        target_topic_id=teacher.id,
        target_topic_source="teacher",
        target_organization_id=org.id,
        copy_content=False,
    )

    assert result.concepts_copied == 1
    assert result.visuals_copied == 2

    cloned = await CurriculumConcept.find(
        CurriculumConcept.topic_id == teacher.id,
        CurriculumConcept.topic_source == "teacher",
    ).to_list()
    assert len(cloned) == 1
    teacher_concept = cloned[0]
    assert teacher_concept.organization_id == org.id
    assert teacher_concept.id != source_concept.id
    assert teacher_concept.teaching_sequence == [
        "story_hook",
        "vtse",
        "visual_teaching",
    ]

    src_reload = await CurriculumConcept.get(source_concept.id)
    assert src_reload is not None
    src_images = src_reload.visual_teaching["images"]
    dst_images = teacher_concept.visual_teaching["images"]
    assert len(dst_images) == 2
    assert [img["asset_key"] for img in dst_images] == [
        "stomata_surface",
        "stomata_cross",
    ]
    assert [img["sort_order"] for img in dst_images] == [0, 1]
    assert [img["teaching_purpose"] for img in dst_images] == [
        "Show the pore opening.",
        "Show guard cell turgor.",
    ]
    assert [img["annotations_status"] for img in dst_images] == ["confirmed", "stale"]

    for src, dst in zip(src_images, dst_images):
        assert dst["id"] != src["id"]
        assert dst["storage_key"] != src["storage_key"]
        assert dst["storage_key"] not in {key_a, key_b}
        assert dst["asset_key"] == src["asset_key"]
        assert dst["regions"][0]["region_id"] == src["regions"][0]["region_id"]
        assert dst["regions"][0]["geometry"] == src["regions"][0]["geometry"]
        assert dst["regions"][0]["focus_point"] == src["regions"][0]["focus_point"]
        assert [a["anchor_id"] for a in dst["anchors"]] == [
            a["anchor_id"] for a in src["anchors"]
        ]
        assert dst["connections"][0]["connection_id"] == src["connections"][0][
            "connection_id"
        ]
        assert await vt_storage.exists(dst["storage_key"]) is True
        assert await vt_storage.exists(src["storage_key"]) is True

    assert await _read_all(vt_storage, dst_images[0]["storage_key"]) == PNG_A
    assert await _read_all(vt_storage, dst_images[1]["storage_key"]) == PNG_B
    assert await _read_all(vt_storage, key_a) == PNG_A
    assert await _read_all(vt_storage, key_b) == PNG_B

    # Teacher edit/delete must not mutate Admin binaries or package.
    teacher_keys = [img["storage_key"] for img in dst_images]
    teacher_concept.visual_teaching = {
        "images": [
            {
                **dst_images[0],
                "teaching_purpose": "Teacher-only rewrite",
                "annotations_status": "stale",
                "regions": [],
                "anchors": [],
                "connections": [],
            }
        ]
    }
    await teacher_concept.save()
    for key in teacher_keys:
        await vt_storage.delete(key)

    src_after = await CurriculumConcept.get(source_concept.id)
    assert src_after is not None
    assert src_after.visual_teaching["images"][0]["teaching_purpose"] == (
        "Show the pore opening."
    )
    assert src_after.visual_teaching["images"][0]["storage_key"] == key_a
    assert src_after.visual_teaching["images"][1]["storage_key"] == key_b
    assert await vt_storage.exists(key_a) is True
    assert await vt_storage.exists(key_b) is True
    assert await _read_all(vt_storage, key_a) == PNG_A
    assert await _read_all(vt_storage, key_b) == PNG_B

    tgt_after = await CurriculumConcept.get(teacher_concept.id)
    assert tgt_after is not None
    assert len(tgt_after.visual_teaching["images"]) == 1
    assert (
        tgt_after.visual_teaching["images"][0]["teaching_purpose"]
        == "Teacher-only rewrite"
    )


@pytest.mark.asyncio
async def test_visual_teaching_clone_aborts_and_cleans_partial_binary_copies(
    db,
    org,
    teacher_user,
    vt_storage,
):
    """Missing second binary must clean the first copied key and write no rows."""
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone

    key_a = await vt_storage.save(
        data=PNG_A, content_type="image/png", key_hint="stomata_surface"
    )
    catalog, source_concept = await _build_admin_vt_tree(
        visual_teaching={
            "images": [
                _image_payload(
                    image_id="img_admin_a",
                    asset_key="stomata_surface",
                    storage_key=key_a,
                    sort_order=0,
                    teaching_purpose="Show the pore opening.",
                    annotations_status="confirmed",
                    region_id="pore_opening",
                    geometry={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    focus_point={"x": 0.25, "y": 0.35},
                    anchor_a="anchor_left",
                    anchor_b="anchor_right",
                    connection_id="conn_flow_1",
                ),
                _image_payload(
                    image_id="img_admin_b",
                    asset_key="stomata_cross",
                    storage_key="missing-vt-binary.png",
                    sort_order=1,
                    teaching_purpose="Show guard cell turgor.",
                    annotations_status="confirmed",
                    region_id="guard_cell",
                    geometry={"x": 0.15, "y": 0.25, "w": 0.35, "h": 0.45},
                    focus_point={"x": 0.4, "y": 0.5},
                    anchor_a="anchor_top",
                    anchor_b="anchor_bottom",
                    connection_id="conn_compare_1",
                ),
            ]
        }
    )
    teacher = await _teacher_topic(org, teacher_user, catalog)

    before = {p.name for p in vt_storage.root.iterdir()} if vt_storage.root.exists() else set()

    with pytest.raises(StorageError):
        await clone_structured_curriculum(
            source_topic_id=catalog.id,
            source_topic_source="catalog",
            source_organization_id=None,
            target_topic_id=teacher.id,
            target_topic_source="teacher",
            target_organization_id=org.id,
            copy_content=False,
        )

    after = {p.name for p in vt_storage.root.iterdir()} if vt_storage.root.exists() else set()
    assert after == before
    assert await vt_storage.exists(key_a) is True
    assert await _read_all(vt_storage, key_a) == PNG_A

    src = await CurriculumConcept.get(source_concept.id)
    assert src is not None
    assert src.visual_teaching["images"][0]["storage_key"] == key_a
    assert (
        await CurriculumZone.find(CurriculumZone.topic_id == teacher.id).to_list() == []
    )
    assert (
        await CurriculumConcept.find(
            CurriculumConcept.topic_id == teacher.id
        ).to_list()
        == []
    )


@pytest.mark.asyncio
async def test_visual_teaching_clone_rolls_back_binaries_when_db_write_fails(
    db,
    org,
    teacher_user,
    vt_storage,
    monkeypatch,
):
    """After successful binary copies, a failed DB write must not leave orphans."""
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone

    key_a = await vt_storage.save(
        data=PNG_A, content_type="image/png", key_hint="stomata_surface"
    )
    key_b = await vt_storage.save(
        data=PNG_B, content_type="image/png", key_hint="stomata_cross"
    )
    catalog, source_concept = await _build_admin_vt_tree(
        visual_teaching={
            "images": [
                _image_payload(
                    image_id="img_admin_a",
                    asset_key="stomata_surface",
                    storage_key=key_a,
                    sort_order=0,
                    teaching_purpose="Show the pore opening.",
                    annotations_status="confirmed",
                    region_id="pore_opening",
                    geometry={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                    focus_point={"x": 0.25, "y": 0.35},
                    anchor_a="anchor_left",
                    anchor_b="anchor_right",
                    connection_id="conn_flow_1",
                ),
                _image_payload(
                    image_id="img_admin_b",
                    asset_key="stomata_cross",
                    storage_key=key_b,
                    sort_order=1,
                    teaching_purpose="Show guard cell turgor.",
                    annotations_status="stale",
                    region_id="guard_cell",
                    geometry={"x": 0.15, "y": 0.25, "w": 0.35, "h": 0.45},
                    focus_point={"x": 0.4, "y": 0.5},
                    anchor_a="anchor_top",
                    anchor_b="anchor_bottom",
                    connection_id="conn_compare_1",
                ),
            ]
        }
    )
    teacher = await _teacher_topic(org, teacher_user, catalog)

    before = {p.name for p in vt_storage.root.iterdir()} if vt_storage.root.exists() else set()
    copied_keys: list[str] = []
    original_copy = vt_storage.copy

    async def tracking_copy(source_key: str, *, key_hint=None):
        new_key = await original_copy(source_key, key_hint=key_hint)
        copied_keys.append(new_key)
        return new_key

    monkeypatch.setattr(vt_storage, "copy", tracking_copy)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("simulated zone create failure after VT binary copy")

    monkeypatch.setattr(
        CurriculumCloneService,
        "_write_cloned_tree",
        boom,
    )

    with pytest.raises(RuntimeError, match="simulated zone create failure"):
        await clone_structured_curriculum(
            source_topic_id=catalog.id,
            source_topic_source="catalog",
            source_organization_id=None,
            target_topic_id=teacher.id,
            target_topic_source="teacher",
            target_organization_id=org.id,
            copy_content=False,
        )

    assert len(copied_keys) == 2
    for key in copied_keys:
        assert await vt_storage.exists(key) is False

    after = {p.name for p in vt_storage.root.iterdir()} if vt_storage.root.exists() else set()
    assert after == before
    assert await vt_storage.exists(key_a) is True
    assert await vt_storage.exists(key_b) is True
    assert await _read_all(vt_storage, key_a) == PNG_A
    assert await _read_all(vt_storage, key_b) == PNG_B

    src = await CurriculumConcept.get(source_concept.id)
    assert src is not None
    assert [img["storage_key"] for img in src.visual_teaching["images"]] == [
        key_a,
        key_b,
    ]
    assert (
        await CurriculumZone.find(CurriculumZone.topic_id == teacher.id).to_list() == []
    )
    assert (
        await CurriculumConcept.find(
            CurriculumConcept.topic_id == teacher.id
        ).to_list()
        == []
    )
