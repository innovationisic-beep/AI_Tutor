"""Tests for resolve_published_topic_v2 (Phase 3B.1A)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.curriculum.topic_context_service import TopicContext
from app.services.runtime.curriculum_resolution_service import (
    CurriculumResolutionError,
    CurriculumResolutionService,
)


def _ctx(*, published: bool = True) -> TopicContext:
    return TopicContext(
        topic_id=PydanticObjectId(),
        topic_source="teacher",
        organization_id=PydanticObjectId(),
        topic_name="Photosynthesis",
        curriculum_schema_version="v2",
        curriculum_revision=3,
        curriculum_published_at=datetime.now(timezone.utc) if published else None,
        supports_class_sessions=True,
        is_catalog=False,
    )


@pytest.mark.asyncio
async def test_resolve_published_topic_v2_builds_keys_from_zone_1():
    zone_id = PydanticObjectId()
    cluster_id = PydanticObjectId()
    concept_a = PydanticObjectId()
    concept_b = PydanticObjectId()

    zone = MagicMock()
    zone.id = zone_id
    zone.zone_number = 1
    zone.status = "published"

    cluster = MagicMock()
    cluster.id = cluster_id
    cluster.curriculum_zone_id = zone_id
    cluster.status = "published"
    cluster.deleted_at = None
    cluster.sort_order = 0

    c1 = MagicMock()
    c1.id = concept_a
    c1.curriculum_cluster_id = cluster_id
    c1.status = "published"
    c1.deleted_at = None
    c1.sort_order = 0
    c1.canonical_runtime_key = "chlorophyll"

    c2 = MagicMock()
    c2.id = concept_b
    c2.curriculum_cluster_id = cluster_id
    c2.status = "published"
    c2.deleted_at = None
    c2.sort_order = 1
    c2.canonical_runtime_key = "light_reactions"

    zone_repo = MagicMock()
    zone_repo.list_by_topic = AsyncMock(return_value=[zone])
    cluster_repo = MagicMock()
    cluster_repo.list_by_topic = AsyncMock(return_value=[cluster])
    concept_repo = MagicMock()
    concept_repo.list_by_topic = AsyncMock(return_value=[c1, c2])

    service = CurriculumResolutionService(
        zone_repo=zone_repo,
        cluster_repo=cluster_repo,
        concept_repo=concept_repo,
    )
    manifest = await service.resolve_published_topic_v2(_ctx())
    assert manifest.key_concepts == ["chlorophyll", "light_reactions"]
    assert manifest.concept_clusters == [["chlorophyll", "light_reactions"]]
    assert manifest.launch_context.resolution_mode == "published_topic_v2"
    assert manifest.launch_context.curriculum_revision == 3


@pytest.mark.asyncio
async def test_resolve_published_topic_v2_skips_zone_0():
    zone0_id = PydanticObjectId()
    zone1_id = PydanticObjectId()

    zone0 = MagicMock()
    zone0.id = zone0_id
    zone0.zone_number = 0
    zone0.status = "published"

    zone1 = MagicMock()
    zone1.id = zone1_id
    zone1.zone_number = 1
    zone1.status = "published"

    cluster = MagicMock()
    cluster.id = PydanticObjectId()
    cluster.curriculum_zone_id = zone1_id
    cluster.status = "published"
    cluster.deleted_at = None
    cluster.sort_order = 0

    concept = MagicMock()
    concept.id = PydanticObjectId()
    concept.curriculum_cluster_id = cluster.id
    concept.status = "published"
    concept.deleted_at = None
    concept.sort_order = 0
    concept.canonical_runtime_key = "core_idea"

    zone_repo = MagicMock()
    zone_repo.list_by_topic = AsyncMock(return_value=[zone0, zone1])
    cluster_repo = MagicMock()
    cluster_repo.list_by_topic = AsyncMock(return_value=[cluster])
    concept_repo = MagicMock()
    concept_repo.list_by_topic = AsyncMock(return_value=[concept])

    manifest = await CurriculumResolutionService(
        zone_repo=zone_repo,
        cluster_repo=cluster_repo,
        concept_repo=concept_repo,
    ).resolve_published_topic_v2(_ctx())
    assert manifest.key_concepts == ["core_idea"]


@pytest.mark.asyncio
async def test_resolve_published_topic_v2_requires_publish():
    with pytest.raises(CurriculumResolutionError) as exc:
        await CurriculumResolutionService().resolve_published_topic_v2(
            _ctx(published=False)
        )
    assert exc.value.code == "NOT_PUBLISHED"


def test_zone_coverage_skipped_in_class_session_resolution():
    zone_id = PydanticObjectId()
    cluster_id = PydanticObjectId()
    from app.models.classroom.class_session_plan import ClassSessionPlanItem
    from app.models.classroom.class_session_instance import (
        ClassSessionInstance,
        ClassSessionPlanSnapshot,
    )

    items = [
        ClassSessionPlanItem(
            sort_order=0,
            item_type="zone_coverage",
            curriculum_zone_id=zone_id,
            zone_number=0,
        ),
        ClassSessionPlanItem(
            sort_order=1,
            item_type="cluster_coverage",
            curriculum_zone_id=zone_id,
            curriculum_cluster_id=cluster_id,
            zone_number=1,
            resolved_runtime_keys=["only_key"],
            resolved_concept_ids=[PydanticObjectId()],
        ),
    ]
    instance = ClassSessionInstance.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        class_session_plan_id=PydanticObjectId(),
        teacher_topic_id=PydanticObjectId(),
        class_id="class-10a",
        subject_id="science",
        primary_teacher_id=PydanticObjectId(),
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc),
        plan_snapshot=ClassSessionPlanSnapshot(
            plan_id=PydanticObjectId(),
            title="Session 1",
            sequence_number=1,
            curriculum_revision=1,
            items=items,
        ),
        status="scheduled",
    )
    manifest = CurriculumResolutionService().resolve_class_session(instance)
    assert manifest.key_concepts == ["only_key"]
