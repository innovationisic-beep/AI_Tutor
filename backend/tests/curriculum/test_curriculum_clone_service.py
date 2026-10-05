"""Tests for clone_structured_curriculum (Phase 3B.1B)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.services.curriculum.curriculum_clone_service import clone_structured_curriculum
from app.services.storage.story_hook_storage import (
    LocalStoryHookStorage,
    StorageError,
    set_story_hook_storage,
)


@pytest.fixture()
def story_hook_storage(tmp_path):
    """Swap in a temp-dir provider; callers only ever see opaque storage keys."""
    storage = LocalStoryHookStorage(tmp_path / "story_hook")
    set_story_hook_storage(storage)
    try:
        yield storage
    finally:
        set_story_hook_storage(None)


async def _build_catalog_tree(*, story_hook: dict | None) -> tuple[Topic, object]:
    from app.models.curriculum.curriculum_cluster import CurriculumCluster
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone

    catalog = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Transpiration",
        topic_slug="transpiration",
        topic_description="Story hook visuals clone",
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
        slug="stomata",
        display_name="Stomata",
        canonical_runtime_key="stomata",
        story_hook=story_hook,
        teaching_sequence=["story_hook", "vtse"],
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
async def test_clone_structured_curriculum_copies_tree_and_metadata(
    db,
    org,
    teacher_user,
):
    catalog = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Photosynthesis Clone",
        topic_slug="photosynthesis-clone",
        topic_description="Test topic for clone",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        curriculum_revision=2,
        curriculum_published_at=datetime.now(timezone.utc),
        supports_class_sessions=True,
        key_concepts=["old_flat"],
    )
    await catalog.insert()

    from app.models.curriculum.curriculum_zone import CurriculumZone
    from app.models.curriculum.curriculum_cluster import CurriculumCluster
    from app.models.curriculum.curriculum_concept import CurriculumConcept

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
    await CurriculumConcept(
        organization_id=None,
        topic_id=catalog.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        curriculum_cluster_id=cluster.id,
        slug="chlorophyll",
        display_name="Chlorophyll",
        canonical_runtime_key="chlorophyll",
        study_points=["Study chlorophyll"],
        learning_outcomes=["Explain chlorophyll"],
        story_hook={
            "title": "Green leaf story",
            "body": "Leaves capture sunlight.",
        },
        teaching_sequence=["story_hook", "vtse", "media"],
        vtse_template={
            "strategy_id": "comparison_contrast",
            "version": 1,
            "payload": {
                "left_label": "Plant",
                "right_label": "Animal",
                "rows": [
                    {
                        "dimension": "Energy",
                        "left_detail": "Makes food",
                        "right_detail": "Eats food",
                    },
                    {
                        "dimension": "Movement",
                        "left_detail": "Rooted",
                        "right_detail": "Moves",
                    },
                ],
            },
        },
        status="published",
    ).insert()

    teacher = TeacherTopic(
        organization_id=org.id,
        teacher_id=teacher_user.id,
        class_id="c1",
        subject_id="s1",
        topic_name="Photosynthesis Clone",
        key_concepts=["stale"],
        curriculum_topic_id=catalog.id,
    )
    await teacher.insert()

    result = await clone_structured_curriculum(
        source_topic_id=catalog.id,
        source_topic_source="catalog",
        source_organization_id=None,
        target_topic_id=teacher.id,
        target_topic_source="teacher",
        target_organization_id=org.id,
        copy_content=False,
    )

    assert result.zones_copied == 1
    assert result.clusters_copied == 1
    assert result.concepts_copied == 1
    assert result.metadata_synced is True

    reloaded = await TeacherTopic.get(teacher.id)
    assert reloaded is not None
    assert reloaded.curriculum_schema_version == "v2"
    assert reloaded.curriculum_published_at is not None
    assert "chlorophyll" in (reloaded.key_concepts or [])

    tgt_zones = await CurriculumZone.find(
        CurriculumZone.topic_id == teacher.id,
        CurriculumZone.topic_source == "teacher",
    ).to_list()
    assert len(tgt_zones) == 1

    tgt_concepts = await CurriculumConcept.find(
        CurriculumConcept.topic_id == teacher.id,
        CurriculumConcept.topic_source == "teacher",
    ).to_list()
    assert len(tgt_concepts) == 1
    assert tgt_concepts[0].study_points == ["Study chlorophyll"]
    assert tgt_concepts[0].learning_outcomes == ["Explain chlorophyll"]
    assert tgt_concepts[0].story_hook is not None
    assert tgt_concepts[0].story_hook["title"] == "Green leaf story"
    assert tgt_concepts[0].story_hook["body"] == "Leaves capture sunlight."
    assert tgt_concepts[0].teaching_sequence == ["story_hook", "vtse", "media"]
    assert tgt_concepts[0].vtse_template is not None
    assert tgt_concepts[0].vtse_template["strategy_id"] == "comparison_contrast"
    assert tgt_concepts[0].vtse_template["payload"]["left_label"] == "Plant"
    assert tgt_concepts[0].organization_id == org.id

    # Teacher copy is independently editable; catalog source stays unchanged.
    source_concepts = await CurriculumConcept.find(
        CurriculumConcept.topic_id == catalog.id,
        CurriculumConcept.topic_source == "catalog",
    ).to_list()
    assert len(source_concepts) == 1
    assert tgt_concepts[0].id != source_concepts[0].id
    tgt_concepts[0].study_points = ["Teacher-only edit"]
    tgt_concepts[0].learning_outcomes = ["Teacher-only outcome"]
    tgt_concepts[0].story_hook = {
        "title": "Teacher hook",
        "body": "Independent",
    }
    tgt_concepts[0].teaching_sequence = ["vtse"]
    await tgt_concepts[0].save()
    reloaded_source = await CurriculumConcept.get(source_concepts[0].id)
    assert reloaded_source is not None
    assert reloaded_source.study_points == ["Study chlorophyll"]
    assert reloaded_source.learning_outcomes == ["Explain chlorophyll"]
    assert reloaded_source.story_hook is not None
    assert reloaded_source.story_hook["title"] == "Green leaf story"
    assert reloaded_source.teaching_sequence == ["story_hook", "vtse", "media"]
    assert reloaded_source.vtse_template is not None
    assert reloaded_source.vtse_template["strategy_id"] == "comparison_contrast"
    reloaded_target = await CurriculumConcept.get(tgt_concepts[0].id)
    assert reloaded_target is not None
    assert reloaded_target.study_points == ["Teacher-only edit"]
    assert reloaded_target.learning_outcomes == ["Teacher-only outcome"]
    assert reloaded_target.story_hook is not None
    assert reloaded_target.story_hook["title"] == "Teacher hook"
    assert reloaded_target.teaching_sequence == ["vtse"]


@pytest.mark.asyncio
async def test_clone_duplicates_story_hook_visual_binaries(
    db,
    org,
    teacher_user,
    story_hook_storage,
):
    """The teacher copy must own its own objects — never the catalog's keys."""
    from app.models.curriculum.curriculum_concept import CurriculumConcept

    source_key = await story_hook_storage.save(
        data=b"\x89PNG\r\n\x1a\nleaf-surface",
        content_type="image/png",
        key_hint="stomata_surface",
    )
    catalog, _ = await _build_catalog_tree(
        story_hook={
            "title": "Leaf pores",
            "body": "A leaf breathing through tiny doors.",
            "teacher_intent": "Emphasise guard cell control.",
            "visuals": [
                {
                    "id": "v1",
                    "asset_key": "stomata_surface",
                    "storage_key": source_key,
                    "description": "Microscope view of a stoma.",
                    "teaching_purpose": "Show the pore and guard cells.",
                    "mime_type": "image/png",
                    "sort_order": 0,
                }
            ],
        }
    )
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

    assert result.visuals_copied == 1
    cloned = await CurriculumConcept.find(
        CurriculumConcept.topic_id == teacher.id,
        CurriculumConcept.topic_source == "teacher",
    ).to_list()
    visual = cloned[0].story_hook["visuals"][0]

    # asset_key is the planner's handle and must survive; identity and bytes move.
    assert visual["asset_key"] == "stomata_surface"
    assert visual["teaching_purpose"] == "Show the pore and guard cells."
    assert visual["storage_key"] != source_key
    assert visual["id"] != "v1"
    assert await story_hook_storage.exists(visual["storage_key"]) is True

    # Deleting the teacher's object leaves the catalog original intact.
    await story_hook_storage.delete(visual["storage_key"])
    assert await story_hook_storage.exists(source_key) is True


@pytest.mark.asyncio
async def test_clone_aborts_before_writing_rows_when_a_binary_copy_fails(
    db,
    org,
    teacher_user,
    story_hook_storage,
):
    """A dangling image reference is worse than a failed import."""
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.models.curriculum.curriculum_zone import CurriculumZone

    catalog, _ = await _build_catalog_tree(
        story_hook={
            "title": "Leaf pores",
            "body": "A leaf breathing through tiny doors.",
            "visuals": [
                {
                    "asset_key": "missing_asset",
                    "storage_key": "gone-forever.png",
                    "description": "Never uploaded.",
                }
            ],
        }
    )
    teacher = await _teacher_topic(org, teacher_user, catalog)

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

    assert (
        await CurriculumZone.find(CurriculumZone.topic_id == teacher.id).to_list() == []
    )
    assert (
        await CurriculumConcept.find(
            CurriculumConcept.topic_id == teacher.id
        ).to_list()
        == []
    )
