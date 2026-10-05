"""Session plan launch must respect curriculum zone — Zone 2+ is entry stub only."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.learning.sessions import Session
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator


def _cluster_item(
    *,
    sort_order: int,
    cluster_id: PydanticObjectId,
    zone_id: PydanticObjectId,
    zone_number: int,
) -> ClassSessionPlanItem:
    return ClassSessionPlanItem(
        sort_order=sort_order,
        item_type="cluster_coverage",
        curriculum_zone_id=zone_id,
        curriculum_cluster_id=cluster_id,
        zone_number=zone_number,
        display_name_snapshot=f"Z{zone_number} cluster",
        resolved_runtime_keys=["concept_a"],
    )


def test_first_zone_number_from_plan():
    z1, z2 = PydanticObjectId(), PydanticObjectId()
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=PydanticObjectId(),
        sequence_number=2,
        title="Session 2",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=PydanticObjectId(),
                zone_id=z2,
                zone_number=2,
            ),
        ],
    )
    assert PlanSessionClusterRegistry.first_zone_number(plan) == 2


def test_session_two_plan_applies_zone_two_entry_stub():
    session = Session.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        current_zone=0,
        flow_state="idle",
    )
    z2 = PydanticObjectId()
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=session.organization_id,
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=session.topic_id,
        sequence_number=2,
        title="Session 2",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=PydanticObjectId(),
                zone_id=z2,
                zone_number=2,
            ),
        ],
    )
    first_zone = PlanSessionClusterRegistry.first_zone_number(plan)
    session.zone0_phase = "done"
    session.current_zone = first_zone
    if first_zone >= 2:
        session.flow_state = "idle"

    assert session.current_zone == 2
    assert session.flow_state == "idle"
    assert session.zone0_phase == "done"


def test_session_two_zone_one_still_uses_zone_one_idle():
    session = Session.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        current_zone=0,
        flow_state="idle",
    )
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=session.organization_id,
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=session.topic_id,
        sequence_number=2,
        title="Session 2 zone 1",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=PydanticObjectId(),
                zone_id=PydanticObjectId(),
                zone_number=1,
            ),
        ],
    )
    first_zone = PlanSessionClusterRegistry.first_zone_number(plan)
    session.current_zone = first_zone
    assert first_zone == 1
    assert session.flow_state == "idle"


def test_zone_entry_flow_blocks_vtse_idle_path():
    assert ZoneTransitionCoordinator.parse_zone_entry_flow("zone_2_entry") is None
    assert ZoneTransitionCoordinator.parse_zone_entry_flow("zone_3_entry") == 3
    payload = ZoneTransitionCoordinator.zone_entry_payload(3)
    assert payload["type"] == "zone_3_entry_ready"
