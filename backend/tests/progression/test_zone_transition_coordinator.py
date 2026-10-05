"""Zone transition gate — unified runtime path tests."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.learning.sessions import Session
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator


def _cluster_item(
    *,
    sort_order: int,
    cluster_id: PydanticObjectId,
    zone_id: PydanticObjectId,
    zone_number: int,
    keys: list[str] | None = None,
) -> ClassSessionPlanItem:
    return ClassSessionPlanItem(
        sort_order=sort_order,
        item_type="cluster_coverage",
        curriculum_zone_id=zone_id,
        curriculum_cluster_id=cluster_id,
        zone_number=zone_number,
        display_name_snapshot=f"Z{zone_number} cluster",
        resolved_runtime_keys=keys or ["concept_a"],
    )


def _session_with_plan(
    plan: ClassSessionPlan,
    *,
    current_zone: int = 1,
    concept_index: int = 2,
    key_concepts: list[str] | None = None,
) -> Session:
    kc = key_concepts or ["c1", "c2", "c3"]
    clusters = [[c] for c in kc]
    return Session.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        progression_session_plan_id=plan.id,
        current_zone=current_zone,
        current_concept_index=concept_index,
        total_concepts=len(kc),
        key_concepts=kc,
        concept_clusters=clusters,
        flow_state="idle",
        current_mode="normal",
    )


@pytest.mark.asyncio
async def test_session_end_after_zone1_only_triggers_gate(monkeypatch):
    """Session 1 = Zone 1 only; gate runs before session completes."""
    z1_id = PydanticObjectId()
    c1 = PydanticObjectId()
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=PydanticObjectId(),
        sequence_number=1,
        title="Session 1",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=c1,
                zone_id=z1_id,
                zone_number=1,
                keys=["c1", "c2"],
            ),
        ],
    )
    session = _session_with_plan(
        plan,
        current_zone=1,
        concept_index=2,
        key_concepts=["c1", "c2"],
    )
    coordinator = ZoneTransitionCoordinator()

    async def _load(_session):
        return plan

    async def _next_zone(*_a, **_k):
        return 2

    monkeypatch.setattr(coordinator, "load_plan", _load)
    monkeypatch.setattr(coordinator, "_next_zone_after_session_slice", _next_zone)

    decision = await coordinator.decide_after_cluster_teachback(session, topic_done=True)
    assert decision.needs_gate is True
    assert decision.from_zone == 1
    assert decision.target_zone == 2
    assert decision.complete_session_after_gate is True


@pytest.mark.asyncio
async def test_in_session_zone_transition_without_session_end(monkeypatch):
    """Session spans Zone 1 and Zone 2 — gate mid-session, no completion."""
    z1_id, z2_id = PydanticObjectId(), PydanticObjectId()
    c1, c2 = PydanticObjectId(), PydanticObjectId()
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=PydanticObjectId(),
        sequence_number=1,
        title="Session 1",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=c1,
                zone_id=z1_id,
                zone_number=1,
                keys=["c1"],
            ),
            _cluster_item(
                sort_order=1,
                cluster_id=c2,
                zone_id=z2_id,
                zone_number=2,
                keys=["c2"],
            ),
        ],
    )
    session = _session_with_plan(
        plan,
        current_zone=1,
        concept_index=1,
        key_concepts=["c1", "c2"],
    )
    coordinator = ZoneTransitionCoordinator()

    async def _load(_session):
        return plan

    monkeypatch.setattr(coordinator, "load_plan", _load)

    decision = await coordinator.decide_after_cluster_teachback(session, topic_done=False)
    assert decision.needs_gate is True
    assert decision.from_zone == 1
    assert decision.target_zone == 2
    assert decision.complete_session_after_gate is False


@pytest.mark.asyncio
async def test_complete_gate_zone2_entry_stub():
    session = Session.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        zone_transition_target_zone=2,
        zone_transition_complete_session=False,
        clarity_gate_active=True,
        current_zone=1,
        current_concept_index=1,
        key_concepts=["c1", "c2"],
    )
    coordinator = ZoneTransitionCoordinator()
    result = coordinator.complete_gate(session)
    assert result.response_type == "teachback_passed"
    assert session.flow_state == "idle"
    assert session.current_zone == 2


@pytest.mark.asyncio
async def test_no_gate_when_same_zone(monkeypatch):
    z1_id = PydanticObjectId()
    c1 = PydanticObjectId()
    plan = ClassSessionPlan.model_construct(
        id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        teacher_id=PydanticObjectId(),
        plan_scope="catalog",
        catalog_topic_id=PydanticObjectId(),
        sequence_number=1,
        title="Session 1",
        status="published",
        items=[
            _cluster_item(
                sort_order=0,
                cluster_id=c1,
                zone_id=z1_id,
                zone_number=1,
                keys=["c1", "c2"],
            ),
        ],
    )
    session = _session_with_plan(plan, current_zone=1, concept_index=2, key_concepts=["c1", "c2"])
    coordinator = ZoneTransitionCoordinator()

    async def _load(_session):
        return plan

    async def _next_zone(*_a, **_k):
        return None

    monkeypatch.setattr(coordinator, "load_plan", _load)
    monkeypatch.setattr(coordinator, "_next_zone_after_session_slice", _next_zone)

    decision = await coordinator.decide_after_cluster_teachback(session, topic_done=True)
    assert decision.needs_gate is False
    assert decision.complete_session_after_gate is True
