"""Classroom planning APIs (Phase 3A — teacher planning only)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.schemas.classroom import (
    ClassSessionPlanOut,
    ClassSessionInstanceOut,
    CreateClassSessionInstanceRequest,
    CreateClassSessionPlanRequest,
    EnrollStudentsRequest,
    EnrollmentOut,
    RescheduleInstanceRequest,
    SetPlanItemsRequest,
    UpdateClassSessionPlanRequest,
    UpdateEnrollmentRequest,
    enrollment_to_out,
    instance_to_out,
    plan_to_out,
)
from app.core.dependencies import get_current_teacher_or_admin
from app.models.classroom.class_session_plan import ClassSessionPlanItem
from app.models.identification.users import User
from app.repositories.student_plan_enrollment_repository import (
    StudentPlanEnrollmentRepository,
)
from app.services.classroom.class_session_instance_service import (
    ClassSessionInstanceService,
)
from app.services.classroom.class_session_plan_service import ClassSessionPlanService
from app.services.classroom.student_plan_enrollment_service import (
    StudentPlanEnrollmentService,
)

router = APIRouter(prefix="/classroom", tags=["Classroom planning"])


def _oid(value: str, *, label: str = "id") -> PydanticObjectId:
    try:
        return PydanticObjectId(value.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label}",
        ) from exc


def _items_from_request(body: SetPlanItemsRequest) -> list[ClassSessionPlanItem]:
    out: list[ClassSessionPlanItem] = []
    for raw in body.items:
        data = {
            "item_id": raw.item_id or str(uuid4()),
            "sort_order": raw.sort_order,
            "item_type": raw.item_type,
            "estimated_minutes": raw.estimated_minutes,
            "is_required": raw.is_required,
            "non_curriculum_label": raw.non_curriculum_label,
        }
        if raw.curriculum_zone_id:
            data["curriculum_zone_id"] = _oid(raw.curriculum_zone_id, label="curriculum_zone_id")
        if raw.curriculum_cluster_id:
            data["curriculum_cluster_id"] = _oid(
                raw.curriculum_cluster_id, label="curriculum_cluster_id"
            )
        if raw.curriculum_concept_id:
            data["curriculum_concept_id"] = _oid(
                raw.curriculum_concept_id, label="curriculum_concept_id"
            )
        if raw.zone_number is not None:
            data["zone_number"] = raw.zone_number
        out.append(ClassSessionPlanItem(**data))
    return out


@router.post("/plans", status_code=status.HTTP_201_CREATED, response_model=ClassSessionPlanOut)
async def create_class_session_plan(
    body: CreateClassSessionPlanRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().create_draft(
        current_user,
        teacher_topic_id=_oid(body.teacher_topic_id, label="teacher_topic_id"),
        class_id=body.class_id,
        subject_id=body.subject_id,
        sequence_number=body.sequence_number,
        title=body.title,
        description=body.description,
        target_duration_minutes=body.target_duration_minutes,
        teacher_notes=body.teacher_notes,
    )
    return plan_to_out(plan)


@router.get("/plans", response_model=list[ClassSessionPlanOut])
async def list_class_session_plans(
    teacher_topic_id: str,
    class_id: str,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> list[ClassSessionPlanOut]:
    plans = await ClassSessionPlanService().list_plans(
        current_user,
        teacher_topic_id=_oid(teacher_topic_id, label="teacher_topic_id"),
        class_id=class_id,
        status=status,
    )
    return [plan_to_out(p) for p in plans]


@router.get("/plans/{plan_id}", response_model=ClassSessionPlanOut)
async def get_class_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().get(_oid(plan_id), current_user)
    return plan_to_out(plan)


@router.put("/plans/{plan_id}", response_model=ClassSessionPlanOut)
async def update_class_session_plan(
    plan_id: str,
    body: UpdateClassSessionPlanRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().update_draft(
        _oid(plan_id),
        current_user,
        title=body.title,
        description=body.description,
        session_study_points=body.session_study_points,
        session_learning_outcomes=body.session_learning_outcomes,
        sequence_number=body.sequence_number,
        target_duration_minutes=body.target_duration_minutes,
        teacher_notes=body.teacher_notes,
    )
    return plan_to_out(plan)


@router.put("/plans/{plan_id}/items", response_model=ClassSessionPlanOut)
async def set_class_session_plan_items(
    plan_id: str,
    body: SetPlanItemsRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().set_items(
        _oid(plan_id),
        current_user,
        _items_from_request(body),
    )
    return plan_to_out(plan)


@router.post("/plans/{plan_id}/validate")
async def validate_class_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    return await ClassSessionPlanService().validate(_oid(plan_id), current_user)


@router.post("/plans/{plan_id}/publish", response_model=ClassSessionPlanOut)
async def publish_class_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().publish(_oid(plan_id), current_user)
    return plan_to_out(plan)


@router.post("/plans/{plan_id}/unpublish", response_model=ClassSessionPlanOut)
async def unpublish_class_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().unpublish(_oid(plan_id), current_user)
    return plan_to_out(plan)


@router.post("/plans/{plan_id}/archive", response_model=ClassSessionPlanOut)
async def archive_class_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().archive(_oid(plan_id), current_user)
    return plan_to_out(plan)


@router.post("/instances", status_code=status.HTTP_201_CREATED, response_model=ClassSessionInstanceOut)
async def create_class_session_instance(
    body: CreateClassSessionInstanceRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    co_ids = [_oid(x, label="co_teacher_id") for x in body.co_teacher_ids]
    inst = await ClassSessionInstanceService().create_from_plan(
        current_user,
        plan_id=_oid(body.class_session_plan_id, label="class_session_plan_id"),
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
        timezone=body.timezone,
        co_teacher_ids=co_ids,
    )
    return instance_to_out(inst, enrollment_count=0)


@router.get("/instances", response_model=list[ClassSessionInstanceOut])
async def list_class_session_instances(
    class_id: str,
    status: Optional[str] = None,
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> list[ClassSessionInstanceOut]:
    instances = await ClassSessionInstanceService().list_instances(
        current_user,
        class_id=class_id,
        status=status,
        from_time=from_time,
        to_time=to_time,
    )
    enroll_repo = StudentPlanEnrollmentRepository()
    out: list[ClassSessionInstanceOut] = []
    for inst in instances:
        count = await enroll_repo.count_for_instance(inst.id)
        out.append(instance_to_out(inst, enrollment_count=count))
    return out


@router.get("/instances/{instance_id}", response_model=ClassSessionInstanceOut)
async def get_class_session_instance(
    instance_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    inst = await ClassSessionInstanceService().get(_oid(instance_id), current_user)
    count = await StudentPlanEnrollmentRepository().count_for_instance(inst.id)
    return instance_to_out(inst, enrollment_count=count)


@router.patch("/instances/{instance_id}", response_model=ClassSessionInstanceOut)
async def reschedule_class_session_instance(
    instance_id: str,
    body: RescheduleInstanceRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    inst = await ClassSessionInstanceService().reschedule(
        _oid(instance_id),
        current_user,
        scheduled_start=body.scheduled_start,
        scheduled_end=body.scheduled_end,
        timezone=body.timezone,
    )
    count = await StudentPlanEnrollmentRepository().count_for_instance(inst.id)
    return instance_to_out(inst, enrollment_count=count)


@router.post("/instances/{instance_id}/cancel", response_model=ClassSessionInstanceOut)
async def cancel_class_session_instance(
    instance_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    inst = await ClassSessionInstanceService().cancel(_oid(instance_id), current_user)
    count = await StudentPlanEnrollmentRepository().count_for_instance(inst.id)
    return instance_to_out(inst, enrollment_count=count)


@router.post("/instances/{instance_id}/start", response_model=ClassSessionInstanceOut)
async def start_class_session_instance(
    instance_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    inst = await ClassSessionInstanceService().mark_live(_oid(instance_id), current_user)
    count = await StudentPlanEnrollmentRepository().count_for_instance(inst.id)
    return instance_to_out(inst, enrollment_count=count)


@router.post("/instances/{instance_id}/complete", response_model=ClassSessionInstanceOut)
async def complete_class_session_instance(
    instance_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> ClassSessionInstanceOut:
    inst = await ClassSessionInstanceService().mark_complete(_oid(instance_id), current_user)
    count = await StudentPlanEnrollmentRepository().count_for_instance(inst.id)
    return instance_to_out(inst, enrollment_count=count)


@router.get("/instances/{instance_id}/enrollments", response_model=list[EnrollmentOut])
async def list_instance_enrollments(
    instance_id: str,
    enrollment_status: Optional[str] = None,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> list[EnrollmentOut]:
    rows = await StudentPlanEnrollmentService().list_enrollments(
        _oid(instance_id),
        current_user,
        enrollment_status=enrollment_status,
    )
    return [enrollment_to_out(r) for r in rows]


@router.post("/instances/{instance_id}/enrollments", response_model=list[EnrollmentOut])
async def enroll_students_to_instance(
    instance_id: str,
    body: EnrollStudentsRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> list[EnrollmentOut]:
    svc = StudentPlanEnrollmentService()
    iid = _oid(instance_id)
    if body.whole_class:
        rows = await svc.enroll_whole_class(iid, current_user)
    else:
        ids = [_oid(s, label="student_id") for s in body.student_ids]
        rows = await svc.enroll_students(iid, current_user, ids)
    return [enrollment_to_out(r) for r in rows]


@router.patch(
    "/instances/{instance_id}/enrollments/{student_id}",
    response_model=EnrollmentOut,
)
async def update_instance_enrollment(
    instance_id: str,
    student_id: str,
    body: UpdateEnrollmentRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> EnrollmentOut:
    row = await StudentPlanEnrollmentService().update_status(
        _oid(instance_id),
        _oid(student_id, label="student_id"),
        current_user,
        enrollment_status=body.enrollment_status,
    )
    return enrollment_to_out(row)


@router.delete(
    "/instances/{instance_id}/enrollments/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_instance_enrollment(
    instance_id: str,
    student_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    await StudentPlanEnrollmentService().remove_enrollment(
        _oid(instance_id),
        _oid(student_id, label="student_id"),
        current_user,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
