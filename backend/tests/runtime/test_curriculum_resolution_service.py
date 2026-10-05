"""Unit tests for CurriculumResolutionService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_instance import (
    ClassSessionInstance,
    ClassSessionPlanSnapshot,
)
from app.models.classroom.class_session_plan import ClassSessionPlanItem
from app.services.runtime.curriculum_resolution_service import (
    CurriculumResolutionError,
    CurriculumResolutionService,
)


def _instance_with_items(items: list[ClassSessionPlanItem]) -> ClassSessionInstance:
    plan_id = PydanticObjectId()
    topic_id = PydanticObjectId()
    return ClassSessionInstance.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        class_session_plan_id=plan_id,
        teacher_topic_id=topic_id,
        class_id="class-10a",
        subject_id="science",
        primary_teacher_id=PydanticObjectId(),
        scheduled_start=datetime.now(timezone.utc) + timedelta(days=1),
        scheduled_end=datetime.now(timezone.utc) + timedelta(days=1, hours=1),
        plan_snapshot=ClassSessionPlanSnapshot(
            plan_id=plan_id,
            title="Session 1",
            sequence_number=1,
            curriculum_revision=2,
            items=items,
        ),
        status="scheduled",
    )


def test_cluster_coverage_resolves_materialized_keys():
    cluster_id = PydanticObjectId()
    zone_id = PydanticObjectId()
    items = [
        ClassSessionPlanItem(
            sort_order=0,
            item_type="cluster_coverage",
            curriculum_zone_id=zone_id,
            curriculum_cluster_id=cluster_id,
            zone_number=1,
            resolved_runtime_keys=["concept_1", "concept_2"],
            resolved_concept_ids=[PydanticObjectId(), PydanticObjectId()],
        )
    ]
    manifest = CurriculumResolutionService().resolve_class_session(
        _instance_with_items(items)
    )
    assert manifest.key_concepts == ["concept_1", "concept_2"]
    assert manifest.concept_clusters == [["concept_1", "concept_2"]]
    assert manifest.launch_context.resolution_mode == "class_session_full"
    assert manifest.launch_context.curriculum_revision == 2


def test_non_curriculum_items_skipped():
    cluster_id = PydanticObjectId()
    zone_id = PydanticObjectId()
    items = [
        ClassSessionPlanItem(
            sort_order=0,
            item_type="non_curriculum",
            non_curriculum_label="Break",
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
    manifest = CurriculumResolutionService().resolve_class_session(
        _instance_with_items(items)
    )
    assert manifest.key_concepts == ["only_key"]


def test_missing_materialization_raises():
    cluster_id = PydanticObjectId()
    zone_id = PydanticObjectId()
    items = [
        ClassSessionPlanItem(
            sort_order=0,
            item_type="cluster_coverage",
            curriculum_zone_id=zone_id,
            curriculum_cluster_id=cluster_id,
            zone_number=1,
        )
    ]
    with pytest.raises(CurriculumResolutionError) as exc:
        CurriculumResolutionService().resolve_class_session(_instance_with_items(items))
    assert exc.value.code == "SNAPSHOT_NOT_MATERIALIZED"
