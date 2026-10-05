"""Student classroom session launch (Phase 3B.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.schemas.runtime_launch import (
    LaunchClassSessionRequest,
    LaunchClassSessionResponse,
    ManifestSummaryOut,
)
from app.core.dependencies import get_current_user
from app.models.classroom.class_session_instance import ClassSessionInstance
from app.models.identification.users import User
from app.models.teacher_topic import TeacherTopic
from app.repositories.class_session_instance_repository import (
    ClassSessionInstanceRepository,
)
from app.repositories.student_plan_enrollment_repository import (
    StudentPlanEnrollmentRepository,
)
from app.services.runtime.launch_adapter_service import LaunchAdapterService

router = APIRouter(prefix="/student/classroom", tags=["Student classroom"])


class StudentClassroomInstanceOut(BaseModel):
    id: str
    class_session_plan_id: str
    teacher_topic_id: str
    topic_name: str = ""
    class_id: str
    subject_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str
    status: str
    plan_title: str = ""
    sequence_number: int = 0


class StudentClassroomInstanceListResponse(BaseModel):
    instances: List[StudentClassroomInstanceOut] = Field(default_factory=list)


def _oid(value: str, *, label: str = "id") -> PydanticObjectId:
    try:
        return PydanticObjectId(value.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label}",
        ) from exc


@router.get("/instances", response_model=StudentClassroomInstanceListResponse)
async def list_student_classroom_instances(
    current_user: User = Depends(get_current_user),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by instance status (scheduled, live, completed, cancelled)",
    ),
) -> StudentClassroomInstanceListResponse:
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access required",
        )
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization required",
        )

    enrollments = await StudentPlanEnrollmentRepository().list_for_student(
        current_user.id,
        enrollment_status="enrolled",
    )
    instance_repo = ClassSessionInstanceRepository()
    out: List[StudentClassroomInstanceOut] = []
    for enrollment in enrollments:
        instance = await instance_repo.get_by_id(enrollment.class_session_instance_id)
        if instance is None:
            continue
        if instance.organization_id != current_user.organization_id:
            continue
        if status_filter and instance.status != status_filter:
            continue
        if instance.status not in ("scheduled", "live", "completed"):
            continue
        topic_name = ""
        tt = await TeacherTopic.get(instance.teacher_topic_id)
        if tt is not None:
            topic_name = tt.topic_name
        snap = instance.plan_snapshot
        out.append(
            StudentClassroomInstanceOut(
                id=str(instance.id),
                class_session_plan_id=str(instance.class_session_plan_id),
                teacher_topic_id=str(instance.teacher_topic_id),
                topic_name=topic_name,
                class_id=instance.class_id,
                subject_id=instance.subject_id,
                scheduled_start=instance.scheduled_start,
                scheduled_end=instance.scheduled_end,
                timezone=instance.timezone,
                status=instance.status,
                plan_title=snap.title if snap else "",
                sequence_number=int(snap.sequence_number) if snap else 0,
            )
        )
    out.sort(key=lambda row: row.scheduled_start)
    return StudentClassroomInstanceListResponse(instances=out)


@router.post(
    "/instances/{instance_id}/launch",
    response_model=LaunchClassSessionResponse,
)
async def launch_class_session(
    instance_id: str,
    body: LaunchClassSessionRequest,
    current_user: User = Depends(get_current_user),
) -> LaunchClassSessionResponse:
    service = LaunchAdapterService()
    out: dict[str, Any] = await service.launch_class_session(
        current_user,
        class_session_instance_id=_oid(instance_id, label="instance_id"),
        action=body.action,
    )
    summary = out.get("manifest_summary")
    return LaunchClassSessionResponse(
        type=out["type"],
        session_id=out.get("session_id"),
        message=out.get("message"),
        buttons=out.get("buttons"),
        manifest_summary=(
            ManifestSummaryOut(**summary) if summary is not None else None
        ),
    )
