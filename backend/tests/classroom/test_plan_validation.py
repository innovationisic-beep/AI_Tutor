"""Unit tests for class session plan validation (Phase 3A)."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.services.classroom.class_session_plan_validation_service import (
    ClassSessionPlanValidationService,
)
from app.services.curriculum.topic_context_service import TopicContext


def _item(
    *,
    sort_order: int,
    zone_id: PydanticObjectId,
    cluster_id: PydanticObjectId,
    zone_number: int,
    concept_id: PydanticObjectId | None = None,
) -> ClassSessionPlanItem:
    return ClassSessionPlanItem(
        sort_order=sort_order,
        item_type="concept_coverage" if concept_id else "cluster_coverage",
        curriculum_zone_id=zone_id,
        curriculum_cluster_id=cluster_id,
        curriculum_concept_id=concept_id,
        zone_number=zone_number,
    )


def _zone_coverage_item(*, sort_order: int, zone_id: PydanticObjectId) -> ClassSessionPlanItem:
    return ClassSessionPlanItem(
        sort_order=sort_order,
        item_type="zone_coverage",
        curriculum_zone_id=zone_id,
        zone_number=0,
    )


@pytest.mark.asyncio
async def test_zone_skip_within_plan_is_error(db, teacher_topic, teacher_user):
    z0_id = PydanticObjectId()
    z2_id = PydanticObjectId()
    c2_id = PydanticObjectId()

    z0 = CurriculumZone(
        id=z0_id,
        organization_id=teacher_topic.organization_id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        zone_number=0,
        title="Curiosity",
        purpose="curiosity",
        is_system_zone=True,
        status="published",
    )
    z2 = CurriculumZone(
        id=z2_id,
        organization_id=teacher_topic.organization_id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        zone_number=2,
        title="Extension 1",
        purpose="extension_1",
        status="published",
    )
    await z0.insert()
    await z2.insert()
    cl2 = CurriculumCluster(
        id=c2_id,
        organization_id=teacher_topic.organization_id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        curriculum_zone_id=z2_id,
        cluster_number=1,
        title="C2",
        status="published",
    )
    await cl2.insert()

    teacher_topic.curriculum_schema_version = "v2"
    teacher_topic.supports_class_sessions = True
    await teacher_topic.save()

    plan = ClassSessionPlan(
        organization_id=teacher_topic.organization_id,
        teacher_id=teacher_user.id,
        teacher_topic_id=teacher_topic.id,
        class_id=teacher_topic.class_id,
        subject_id=teacher_topic.subject_id,
        sequence_number=1,
        title="Skip test",
        curriculum_schema_version="v2",
        items=[
            _zone_coverage_item(sort_order=0, zone_id=z0_id),
            _item(sort_order=1, zone_id=z2_id, cluster_id=c2_id, zone_number=2),
        ],
        status="draft",
    )
    await plan.insert()

    ctx = TopicContext(
        topic_id=teacher_topic.id,
        topic_source="teacher",
        organization_id=teacher_topic.organization_id,
        topic_name=teacher_topic.topic_name,
        curriculum_schema_version="v2",
        curriculum_revision=1,
        curriculum_published_at=None,
        supports_class_sessions=True,
        is_catalog=False,
    )
    result = await ClassSessionPlanValidationService().validate_plan(
        plan, ctx, teacher_topic=teacher_topic
    )
    codes = [e.code for e in result.errors]
    assert "ZONE_SKIP" in codes
    assert not result.ready_to_publish


@pytest.mark.asyncio
async def test_cross_plan_zone_skip_is_error(db, teacher_topic, teacher_user):
    z1_id = PydanticObjectId()
    c1_id = PydanticObjectId()
    z1 = CurriculumZone(
        id=z1_id,
        organization_id=teacher_topic.organization_id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        status="published",
    )
    await z1.insert()
    cl1 = CurriculumCluster(
        id=c1_id,
        organization_id=teacher_topic.organization_id,
        topic_id=teacher_topic.id,
        topic_source="teacher",
        curriculum_zone_id=z1_id,
        cluster_number=1,
        title="Core A",
        status="published",
    )
    await cl1.insert()

    teacher_topic.curriculum_schema_version = "v2"
    teacher_topic.supports_class_sessions = True
    await teacher_topic.save()

    plan2 = ClassSessionPlan(
        organization_id=teacher_topic.organization_id,
        teacher_id=teacher_user.id,
        teacher_topic_id=teacher_topic.id,
        class_id=teacher_topic.class_id,
        subject_id=teacher_topic.subject_id,
        sequence_number=2,
        title="Session 2",
        curriculum_schema_version="v2",
        items=[_item(sort_order=0, zone_id=z1_id, cluster_id=c1_id, zone_number=1)],
        status="draft",
    )
    await plan2.insert()

    ctx = TopicContext(
        topic_id=teacher_topic.id,
        topic_source="teacher",
        organization_id=teacher_topic.organization_id,
        topic_name=teacher_topic.topic_name,
        curriculum_schema_version="v2",
        curriculum_revision=1,
        curriculum_published_at=None,
        supports_class_sessions=True,
        is_catalog=False,
    )
    result = await ClassSessionPlanValidationService().validate_plan(
        plan2, ctx, teacher_topic=teacher_topic
    )
    codes = [e.code for e in result.errors]
    assert "ZONE_SKIP" in codes
