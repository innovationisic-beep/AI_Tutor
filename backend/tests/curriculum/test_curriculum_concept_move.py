"""Tests for CurriculumConcept move / reorder within the same zone."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.models.curriculum.topics import Topic
from app.services.curriculum.curriculum_concept_service import CurriculumConceptService
from app.services.curriculum.topic_context_service import TopicContext


async def _seed_topic_with_two_clusters(db):
    topic = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Move Test Topic",
        topic_slug="move-test-topic",
        topic_description="Topic used for concept move tests",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        key_concepts=[],
    )
    await topic.insert()

    zone1 = await CurriculumZone(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        allows_vtse=True,
        status="draft",
    ).insert()
    zone2 = await CurriculumZone(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        zone_number=2,
        title="Ext",
        purpose="extension_1",
        allows_vtse=True,
        status="draft",
    ).insert()

    c1 = await CurriculumCluster(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone1.id,
        cluster_number=1,
        title="Cluster A",
        sort_order=0,
        status="draft",
    ).insert()
    c2 = await CurriculumCluster(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone1.id,
        cluster_number=2,
        title="Cluster B",
        sort_order=1,
        status="draft",
    ).insert()
    c_other_zone = await CurriculumCluster(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone2.id,
        cluster_number=1,
        title="Zone2 Cluster",
        sort_order=0,
        status="draft",
    ).insert()

    a = await CurriculumConcept(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone1.id,
        curriculum_cluster_id=c1.id,
        slug="concept-a",
        display_name="Concept A",
        canonical_runtime_key="concept a",
        sort_order=0,
        study_points=["Study A"],
        learning_outcomes=["Outcome A"],
        status="draft",
    ).insert()
    b = await CurriculumConcept(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone1.id,
        curriculum_cluster_id=c1.id,
        slug="concept-b",
        display_name="Concept B",
        canonical_runtime_key="concept b",
        sort_order=1,
        study_points=["Study B"],
        learning_outcomes=["Outcome B"],
        status="draft",
    ).insert()
    d = await CurriculumConcept(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone1.id,
        curriculum_cluster_id=c2.id,
        slug="concept-d",
        display_name="Concept D",
        canonical_runtime_key="concept d",
        sort_order=0,
        study_points=["Study D"],
        learning_outcomes=["Outcome D"],
        status="draft",
    ).insert()

    ctx = TopicContext(
        topic_id=topic.id,
        topic_source="catalog",
        organization_id=None,
        topic_name=topic.topic_name,
        curriculum_schema_version="v2",
        curriculum_revision=0,
        curriculum_published_at=None,
        supports_class_sessions=False,
        is_catalog=True,
    )
    return {
        "topic": topic,
        "zone1": zone1,
        "zone2": zone2,
        "c1": c1,
        "c2": c2,
        "c_other_zone": c_other_zone,
        "a": a,
        "b": b,
        "d": d,
        "ctx": ctx,
    }


@pytest.mark.asyncio
async def test_reorder_within_same_cluster(db):
    seeded = await _seed_topic_with_two_clusters(db)
    svc = CurriculumConceptService()
    moved = await svc.move(
        seeded["b"].id,
        seeded["ctx"],
        target_cluster_id=seeded["c1"].id,
        target_index=0,
    )
    assert moved.id == seeded["b"].id
    assert moved.curriculum_cluster_id == seeded["c1"].id
    assert moved.canonical_runtime_key == "concept b"
    assert moved.study_points == ["Study B"]

    siblings = await CurriculumConcept.find(
        {
            "curriculum_cluster_id": seeded["c1"].id,
            "deleted_at": None,
        }
    ).sort("+sort_order").to_list()
    assert [str(s.id) for s in siblings] == [str(seeded["b"].id), str(seeded["a"].id)]
    assert [s.sort_order for s in siblings] == [0, 1]


@pytest.mark.asyncio
async def test_move_between_clusters_preserves_identity_and_bullets(db):
    seeded = await _seed_topic_with_two_clusters(db)
    svc = CurriculumConceptService()
    original_id = seeded["b"].id
    moved = await svc.move(
        seeded["b"].id,
        seeded["ctx"],
        target_cluster_id=seeded["c2"].id,
        target_index=0,
    )
    assert moved.id == original_id
    assert moved.slug == "concept-b"
    assert moved.canonical_runtime_key == "concept b"
    assert moved.display_name == "Concept B"
    assert moved.study_points == ["Study B"]
    assert moved.learning_outcomes == ["Outcome B"]
    assert moved.curriculum_cluster_id == seeded["c2"].id

    c1 = await CurriculumConcept.find(
        {"curriculum_cluster_id": seeded["c1"].id, "deleted_at": None}
    ).sort("+sort_order").to_list()
    c2 = await CurriculumConcept.find(
        {"curriculum_cluster_id": seeded["c2"].id, "deleted_at": None}
    ).sort("+sort_order").to_list()
    assert [s.slug for s in c1] == ["concept-a"]
    assert [s.slug for s in c2] == ["concept-b", "concept-d"]
    assert [s.sort_order for s in c2] == [0, 1]


@pytest.mark.asyncio
async def test_cross_zone_move_rejected(db):
    seeded = await _seed_topic_with_two_clusters(db)
    svc = CurriculumConceptService()
    with pytest.raises(HTTPException) as exc:
        await svc.move(
            seeded["a"].id,
            seeded["ctx"],
            target_cluster_id=seeded["c_other_zone"].id,
            target_index=0,
        )
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "CROSS_ZONE_MOVE"


@pytest.mark.asyncio
async def test_published_concept_move_demotes_to_draft(db):
    seeded = await _seed_topic_with_two_clusters(db)
    concept = seeded["a"]
    concept.status = "published"
    await concept.save()
    svc = CurriculumConceptService()
    moved = await svc.move(
        concept.id,
        seeded["ctx"],
        target_cluster_id=seeded["c2"].id,
        target_index=1,
    )
    assert moved.status == "draft"
    assert moved.curriculum_cluster_id == seeded["c2"].id


async def _seed_teacher_topic_with_two_clusters(db, *, organization_id: PydanticObjectId):
    """Teacher-source curriculum with org-scoped zones/clusters/concepts."""
    from app.models.teacher_topic import TeacherTopic

    topic = TeacherTopic(
        organization_id=organization_id,
        teacher_id=PydanticObjectId(),
        class_id="class-a",
        subject_id="subj-a",
        topic_name="Teacher Move Topic",
        key_concepts=[],
        curriculum_schema_version="v2",
    )
    await topic.insert()

    zone1 = await CurriculumZone(
        organization_id=organization_id,
        topic_id=topic.id,
        topic_source="teacher",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        allows_vtse=True,
        status="draft",
    ).insert()

    c1 = await CurriculumCluster(
        organization_id=organization_id,
        topic_id=topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone1.id,
        cluster_number=1,
        title="Cluster A",
        sort_order=0,
        status="draft",
    ).insert()
    c2 = await CurriculumCluster(
        organization_id=organization_id,
        topic_id=topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone1.id,
        cluster_number=2,
        title="Cluster B",
        sort_order=1,
        status="draft",
    ).insert()

    a = await CurriculumConcept(
        organization_id=organization_id,
        topic_id=topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone1.id,
        curriculum_cluster_id=c1.id,
        slug="teacher-a",
        display_name="Teacher A",
        canonical_runtime_key="teacher a",
        sort_order=0,
        study_points=["Teacher Study A"],
        learning_outcomes=["Teacher Outcome A"],
        status="draft",
    ).insert()
    b = await CurriculumConcept(
        organization_id=organization_id,
        topic_id=topic.id,
        topic_source="teacher",
        curriculum_zone_id=zone1.id,
        curriculum_cluster_id=c1.id,
        slug="teacher-b",
        display_name="Teacher B",
        canonical_runtime_key="teacher b",
        sort_order=1,
        study_points=["Teacher Study B"],
        learning_outcomes=["Teacher Outcome B"],
        status="draft",
    ).insert()

    ctx = TopicContext(
        topic_id=topic.id,
        topic_source="teacher",
        organization_id=organization_id,
        topic_name=topic.topic_name,
        curriculum_schema_version="v2",
        curriculum_revision=0,
        curriculum_published_at=None,
        supports_class_sessions=False,
        is_catalog=False,
    )
    return {
        "topic": topic,
        "zone1": zone1,
        "c1": c1,
        "c2": c2,
        "a": a,
        "b": b,
        "ctx": ctx,
    }


@pytest.mark.asyncio
async def test_teacher_move_between_clusters_preserves_identity_and_bullets(db, org):
    seeded = await _seed_teacher_topic_with_two_clusters(db, organization_id=org.id)
    svc = CurriculumConceptService()
    original_id = seeded["b"].id
    moved = await svc.move(
        seeded["b"].id,
        seeded["ctx"],
        target_cluster_id=seeded["c2"].id,
        target_index=0,
    )
    assert moved.id == original_id
    assert moved.topic_source == "teacher"
    assert moved.organization_id == org.id
    assert moved.study_points == ["Teacher Study B"]
    assert moved.learning_outcomes == ["Teacher Outcome B"]
    assert moved.curriculum_cluster_id == seeded["c2"].id

    c1 = await CurriculumConcept.find(
        {"curriculum_cluster_id": seeded["c1"].id, "deleted_at": None}
    ).sort("+sort_order").to_list()
    c2 = await CurriculumConcept.find(
        {"curriculum_cluster_id": seeded["c2"].id, "deleted_at": None}
    ).sort("+sort_order").to_list()
    assert [s.slug for s in c1] == ["teacher-a"]
    assert [s.slug for s in c2] == ["teacher-b"]


@pytest.mark.asyncio
async def test_teacher_cross_organization_move_rejected(db, org):
    seeded = await _seed_teacher_topic_with_two_clusters(db, organization_id=org.id)
    other_org_id = PydanticObjectId()
    foreign_cluster = await CurriculumCluster(
        organization_id=other_org_id,
        topic_id=seeded["topic"].id,
        topic_source="teacher",
        curriculum_zone_id=seeded["zone1"].id,
        cluster_number=9,
        title="Foreign Org Cluster",
        sort_order=9,
        status="draft",
    ).insert()

    svc = CurriculumConceptService()
    with pytest.raises(HTTPException) as exc:
        await svc.move(
            seeded["a"].id,
            seeded["ctx"],
            target_cluster_id=foreign_cluster.id,
            target_index=0,
        )
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "CROSS_ORGANIZATION_MOVE"


@pytest.mark.asyncio
async def test_teacher_cross_source_move_rejected(db, org):
    seeded = await _seed_teacher_topic_with_two_clusters(db, organization_id=org.id)
    catalog_seed = await _seed_topic_with_two_clusters(db)
    svc = CurriculumConceptService()
    with pytest.raises(HTTPException) as exc:
        await svc.move(
            seeded["a"].id,
            seeded["ctx"],
            target_cluster_id=catalog_seed["c1"].id,
            target_index=0,
        )
    # Target cluster is on a different topic → get() 404 before org/source checks,
    # or CROSS_TOPIC / CROSS_SOURCE if get is bypassed. Either is a hard rejection.
    assert exc.value.status_code in (400, 404)
