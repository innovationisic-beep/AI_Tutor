from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.classroom.class_session_instance import (
    ClassSessionInstance,
    ClassSessionPlanSnapshot,
)
from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.identification.users import User
from app.repositories.class_session_instance_repository import (
    ClassSessionInstanceRepository,
)
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.services.runtime.snapshot_materialization_service import (
    SnapshotMaterializationService,
)


class ClassSessionInstanceService:
    def __init__(
        self,
        instance_repo: ClassSessionInstanceRepository | None = None,
        plan_repo: ClassSessionPlanRepository | None = None,
        materialization: SnapshotMaterializationService | None = None,
    ) -> None:
        self._instances = instance_repo or ClassSessionInstanceRepository()
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._materialization = materialization or SnapshotMaterializationService()

    async def _get_instance_for_user(
        self, instance_id: PydanticObjectId, user: User
    ) -> ClassSessionInstance:
        inst = await self._instances.get_by_id(instance_id)
        if inst is None:
            raise HTTPException(status_code=404, detail="Instance not found")
        if user.organization_id is None or inst.organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="Not in your organization")
        if user.role == "teacher" and inst.primary_teacher_id != user.id:
            raise HTTPException(status_code=403, detail="Not your instance")
        return inst

    async def create_from_plan(
        self,
        user: User,
        *,
        plan_id: PydanticObjectId,
        scheduled_start: datetime,
        scheduled_end: datetime,
        timezone: str = "UTC",
        co_teacher_ids: Optional[List[PydanticObjectId]] = None,
    ) -> ClassSessionInstance:
        plan = await self._plans.get_by_id(plan_id)
        if plan is None or plan.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Plan not found")
        if plan.status != "published":
            raise HTTPException(status_code=400, detail="Instance requires a published plan")
        if user.organization_id is None or plan.organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="Plan not in your organization")
        if user.role == "teacher" and plan.teacher_id != user.id:
            raise HTTPException(status_code=403, detail="Not your plan")
        if scheduled_end <= scheduled_start:
            raise HTTPException(status_code=400, detail="scheduled_end must be after scheduled_start")

        materialized_items = await self._materialization.materialize_items(
            [i.model_copy(deep=True) for i in plan.items],
            organization_id=plan.organization_id,
        )
        snapshot = ClassSessionPlanSnapshot(
            plan_id=plan.id,
            title=plan.title,
            sequence_number=plan.sequence_number,
            curriculum_revision=plan.curriculum_revision,
            items=materialized_items,
        )
        return await self._instances.create(
            {
                "organization_id": plan.organization_id,
                "class_session_plan_id": plan.id,
                "teacher_topic_id": plan.teacher_topic_id,
                "class_id": plan.class_id,
                "subject_id": plan.subject_id,
                "primary_teacher_id": user.id,
                "co_teacher_ids": co_teacher_ids or [],
                "scheduled_start": scheduled_start,
                "scheduled_end": scheduled_end,
                "timezone": timezone.strip() or "UTC",
                "plan_snapshot": snapshot,
                "status": "scheduled",
            }
        )

    async def list_instances(
        self,
        user: User,
        *,
        class_id: str,
        status: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
    ) -> List[ClassSessionInstance]:
        if user.organization_id is None:
            raise HTTPException(status_code=403, detail="Organization required")
        try:
            return await self._instances.list_for_class(
                organization_id=user.organization_id,
                class_id=class_id,
                status=status,
                from_time=from_time,
                to_time=to_time,
            )
        except Exception as exc:
            # Corrupt/legacy rows in class_session_instances can fail Beanie parse
            # (ValidationError). Prefer empty calendar over breaking Session Plans UI.
            import logging

            logging.getLogger(__name__).warning(
                "list_instances failed for class_id=%s: %s", class_id, exc
            )
            return []

    async def get(self, instance_id: PydanticObjectId, user: User) -> ClassSessionInstance:
        return await self._get_instance_for_user(instance_id, user)

    async def reschedule(
        self,
        instance_id: PydanticObjectId,
        user: User,
        *,
        scheduled_start: datetime,
        scheduled_end: datetime,
        timezone: Optional[str] = None,
    ) -> ClassSessionInstance:
        inst = await self._get_instance_for_user(instance_id, user)
        if inst.status == "cancelled":
            raise HTTPException(status_code=409, detail="Cancelled instances cannot be rescheduled")
        if scheduled_end <= scheduled_start:
            raise HTTPException(status_code=400, detail="scheduled_end must be after scheduled_start")
        inst.scheduled_start = scheduled_start
        inst.scheduled_end = scheduled_end
        if timezone is not None:
            inst.timezone = timezone.strip() or "UTC"
        await inst.save()
        return inst

    async def cancel(self, instance_id: PydanticObjectId, user: User) -> ClassSessionInstance:
        inst = await self._get_instance_for_user(instance_id, user)
        if inst.status in ("completed", "cancelled"):
            raise HTTPException(status_code=409, detail=f"Cannot cancel instance in status {inst.status}")
        inst.status = "cancelled"
        await inst.save()
        return inst

    async def mark_live(self, instance_id: PydanticObjectId, user: User) -> ClassSessionInstance:
        inst = await self._get_instance_for_user(instance_id, user)
        if inst.status != "scheduled":
            raise HTTPException(status_code=409, detail="Only scheduled instances can go live")
        inst.status = "live"
        inst.actual_start = datetime.utcnow()
        await inst.save()
        return inst

    async def mark_complete(self, instance_id: PydanticObjectId, user: User) -> ClassSessionInstance:
        inst = await self._get_instance_for_user(instance_id, user)
        if inst.status not in ("scheduled", "live"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot complete instance in status {inst.status}",
            )
        inst.status = "completed"
        if inst.actual_start is None:
            inst.actual_start = datetime.utcnow()
        inst.actual_end = datetime.utcnow()
        await inst.save()
        return inst
