"""Phase 3B.2 — session plan progression engine tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.progression.student_plan_progress import StudentPlanProgress
from app.services.progression.plan_progress_coordinator import (
    PlanProgressCoordinator,
    build_plan_track_key,
)
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry
from app.services.progression.release_policy import (
    ImmediateReleasePolicy,
    ScheduledReleasePolicy,
)
from app.services.progression.session_completion_engine import SessionCompletionEngine
from app.services.progression.session_unlock_engine import SessionUnlockEngine
from app.models.runtime.runtime_curriculum_manifest import LaunchContext


def _cluster_item(
    *,
    sort_order: int,
    cluster_id: PydanticObjectId,
    zone_id: PydanticObjectId,
    keys: list[str] | None = None,
    display: str = "Cluster",
) -> ClassSessionPlanItem:
    return ClassSessionPlanItem(
        sort_order=sort_order,
        item_type="cluster_coverage",
        curriculum_zone_id=zone_id,
        curriculum_cluster_id=cluster_id,
        zone_number=1,
        display_name_snapshot=display,
        resolved_runtime_keys=keys or ["concept_a"],
    )


def _plan(
    *,
    seq: int,
    items: list[ClassSessionPlanItem],
    topic_id: PydanticObjectId | None = None,
    plan_id: PydanticObjectId | None = None,
) -> ClassSessionPlan:
    tid = topic_id or PydanticObjectId()
    return ClassSessionPlan.model_construct(
        id=plan_id or PydanticObjectId(),
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=tid,
        sequence_number=seq,
        title=f"Session {seq}",
        status="published",
        items=items,
    )


def test_assigned_clusters_adapts_to_one_or_many():
    zid = PydanticObjectId()
    c1, c2, c3 = PydanticObjectId(), PydanticObjectId(), PydanticObjectId()

    single = _plan(seq=1, items=[_cluster_item(sort_order=0, cluster_id=c1, zone_id=zid)])
    multi = _plan(
        seq=1,
        items=[
            _cluster_item(sort_order=0, cluster_id=c1, zone_id=zid, display="A"),
            _cluster_item(sort_order=1, cluster_id=c2, zone_id=zid, display="B"),
            _cluster_item(sort_order=2, cluster_id=c3, zone_id=zid, display="C"),
        ],
    )

    assert len(PlanSessionClusterRegistry.assigned_clusters(single)) == 1
    assigned = PlanSessionClusterRegistry.assigned_clusters(multi)
    assert len(assigned) == 3
    assert [row.curriculum_cluster_id for row in assigned] == [c1, c2, c3]


def test_session_complete_only_when_all_clusters_done():
    zid = PydanticObjectId()
    c1, c2 = PydanticObjectId(), PydanticObjectId()
    plan = _plan(
        seq=1,
        items=[
            _cluster_item(sort_order=0, cluster_id=c1, zone_id=zid),
            _cluster_item(sort_order=1, cluster_id=c2, zone_id=zid),
        ],
    )
    engine = SessionCompletionEngine()
    progress = StudentPlanProgress.model_construct(
        student_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        plan_track_key="catalog:abc",
        topic_id=PydanticObjectId(),
        plan_scope="catalog",
    )

    partial = engine.evaluate(progress, plan)
    assert partial.is_complete is False
    assert partial.completed_cluster_count == 0

    engine.record_cluster_complete(progress, session_plan_id=plan.id, cluster_id=c1)
    partial = engine.evaluate(progress, plan)
    assert partial.is_complete is False
    assert partial.completed_cluster_count == 1

    engine.record_cluster_complete(progress, session_plan_id=plan.id, cluster_id=c2)
    done = engine.evaluate(progress, plan)
    assert done.is_complete is True
    assert done.completed_cluster_count == 2


@pytest.mark.asyncio
async def test_immediate_release_unlocks_and_auto_starts_next(db):
    topic_id = PydanticObjectId()
    zid = PydanticObjectId()
    c1 = PydanticObjectId()
    plan1 = ClassSessionPlan(
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=topic_id,
        sequence_number=1,
        title="Session 1",
        status="published",
        items=[_cluster_item(sort_order=0, cluster_id=c1, zone_id=zid, display="Cluster 1")],
    )
    plan2 = ClassSessionPlan(
        organization_id=plan1.organization_id,
        teacher_id=plan1.teacher_id,
        plan_scope="catalog",
        catalog_topic_id=topic_id,
        sequence_number=2,
        title="Session 2",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=PydanticObjectId(),
                zone_id=zid,
                display="Cluster 2",
            )
        ],
    )
    await plan1.insert()
    await plan2.insert()

    progress = StudentPlanProgress(
        student_id=PydanticObjectId(),
        organization_id=plan1.organization_id,
        plan_track_key=f"catalog:{topic_id}",
        topic_id=topic_id,
        plan_scope="catalog",
        catalog_topic_id=topic_id,
        current_session_plan_id=plan1.id,
        unlocked_session_plan_ids=[plan1.id],
        status="in_progress",
    )
    await progress.insert()

    unlock = SessionUnlockEngine(release_policy=ImmediateReleasePolicy())
    result = await unlock.on_session_completed(progress, completed_plan_id=plan1.id)

    assert plan1.id in progress.completed_session_plan_ids
    assert plan2.id in progress.unlocked_session_plan_ids
    assert progress.current_session_plan_id == plan2.id
    assert result.auto_start_plan is not None
    assert result.auto_start_plan.id == plan2.id
    assert progress.last_transition is not None
    assert "SESSION 2 STARTED" in str(progress.last_transition.get("title"))


def test_scheduled_release_does_not_auto_start():
    policy = ScheduledReleasePolicy(delay_seconds=3600)
    available = policy.release_at(completed_at=datetime.utcnow())
    assert not policy.is_available_now(available_at=available)
    assert policy.should_auto_start() is False


def test_build_plan_track_key_catalog_and_teacher():
    launch_catalog = LaunchContext(
        launch_kind="personal",
        topic_source="catalog",
        source_topic_id=PydanticObjectId(),
        resolution_mode="catalog_session_plan",
        curriculum_schema_version="v2",
        curriculum_revision=1,
        class_session_plan_id=PydanticObjectId(),
    )
    assert build_plan_track_key(launch=launch_catalog) == (
        f"catalog:{launch_catalog.source_topic_id}"
    )

    launch_teacher = LaunchContext(
        launch_kind="classroom",
        topic_source="teacher",
        source_topic_id=PydanticObjectId(),
        resolution_mode="class_session_full",
        curriculum_schema_version="v2",
        curriculum_revision=1,
        class_session_plan_id=PydanticObjectId(),
        class_id="class-7",
    )
    assert build_plan_track_key(launch=launch_teacher) == (
        f"teacher:{launch_teacher.source_topic_id}:class-7"
    )


def test_learning_path_snapshot_states():
    plan1_id = PydanticObjectId()
    plan2_id = PydanticObjectId()
    plan3_id = PydanticObjectId()
    ordered = [
        ClassSessionPlan.model_construct(
            id=plan1_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=1,
            title="S1",
            status="published",
            items=[],
        ),
        ClassSessionPlan.model_construct(
            id=plan2_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=2,
            title="S2",
            status="published",
            items=[],
        ),
        ClassSessionPlan.model_construct(
            id=plan3_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=3,
            title="S3",
            status="published",
            items=[],
        ),
    ]
    progress = StudentPlanProgress.model_construct(
        student_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        plan_track_key="catalog:x",
        topic_id=PydanticObjectId(),
        completed_session_plan_ids=[plan1_id],
        current_session_plan_id=plan2_id,
        unlocked_session_plan_ids=[plan1_id, plan2_id],
    )
    rows = SessionUnlockEngine().learning_path_snapshot(progress, ordered)
    assert rows[0]["state"] == "completed"
    assert rows[1]["state"] == "active"
    assert rows[2]["state"] == "locked"


def test_learning_path_active_overrides_completed():
    plan1_id = PydanticObjectId()
    plan2_id = PydanticObjectId()
    ordered = [
        ClassSessionPlan.model_construct(
            id=plan1_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=1,
            title="S1",
            status="published",
            items=[],
        ),
        ClassSessionPlan.model_construct(
            id=plan2_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=2,
            title="S2",
            status="published",
            items=[],
        ),
    ]
    progress = StudentPlanProgress.model_construct(
        student_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        plan_track_key="catalog:x",
        topic_id=PydanticObjectId(),
        completed_session_plan_ids=[plan1_id],
        current_session_plan_id=plan1_id,
        unlocked_session_plan_ids=[plan1_id, plan2_id],
    )
    rows = SessionUnlockEngine().learning_path_snapshot(progress, ordered)
    assert rows[0]["state"] == "active"
    assert rows[1]["state"] == "available"


def test_realign_progress_on_plan_start_clears_later_sessions():
    plan1_id = PydanticObjectId()
    plan2_id = PydanticObjectId()
    plan3_id = PydanticObjectId()
    ordered = [
        ClassSessionPlan.model_construct(
            id=plan1_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=1,
            title="S1",
            status="published",
            items=[],
        ),
        ClassSessionPlan.model_construct(
            id=plan2_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=2,
            title="S2",
            status="published",
            items=[],
        ),
        ClassSessionPlan.model_construct(
            id=plan3_id,
            organization_id=PydanticObjectId(),
            teacher_id=PydanticObjectId(),
            plan_scope="catalog",
            catalog_topic_id=PydanticObjectId(),
            sequence_number=3,
            title="S3",
            status="published",
            items=[],
        ),
    ]
    progress = StudentPlanProgress.model_construct(
        student_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        plan_track_key="catalog:x",
        topic_id=PydanticObjectId(),
        completed_session_plan_ids=[plan1_id, plan2_id],
        current_session_plan_id=plan3_id,
        unlocked_session_plan_ids=[plan1_id, plan2_id, plan3_id],
        completed_clusters_by_session={
            str(plan1_id): [str(PydanticObjectId())],
            str(plan2_id): [str(PydanticObjectId())],
        },
    )
    PlanProgressCoordinator()._realign_progress_on_plan_start(
        progress, ordered[0], ordered
    )
    assert progress.completed_session_plan_ids == []
    assert progress.current_session_plan_id == plan1_id
    assert progress.unlocked_session_plan_ids == [plan1_id]
    assert str(plan1_id) not in progress.completed_clusters_by_session
    assert str(plan2_id) not in progress.completed_clusters_by_session
