from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.classroom.class_session_instance import ClassSessionInstance
from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem
from app.models.classroom.student_plan_enrollment import StudentPlanEnrollment


class PlanItemIn(BaseModel):
    item_id: Optional[str] = None
    sort_order: int = Field(..., ge=0)
    item_type: Literal[
        "zone_coverage",
        "cluster_coverage",
        "concept_coverage",
        "non_curriculum",
    ]
    curriculum_zone_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    curriculum_cluster_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    curriculum_concept_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    zone_number: Optional[int] = Field(default=None, ge=0, le=4)
    estimated_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    is_required: bool = True
    non_curriculum_label: Optional[str] = Field(default=None, max_length=200)


class PlanItemOut(BaseModel):
    item_id: str
    sort_order: int
    item_type: str
    curriculum_zone_id: Optional[str] = None
    curriculum_cluster_id: Optional[str] = None
    curriculum_concept_id: Optional[str] = None
    zone_number: Optional[int] = None
    canonical_runtime_key_snapshot: Optional[str] = None
    display_name_snapshot: Optional[str] = None
    estimated_minutes: Optional[int] = None
    is_required: bool
    non_curriculum_label: Optional[str] = None


class CreateClassSessionPlanRequest(BaseModel):
    teacher_topic_id: str = Field(..., min_length=24, max_length=24)
    class_id: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=64)
    sequence_number: int = Field(..., ge=1, le=500)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    target_duration_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    teacher_notes: str = Field(default="", max_length=4000)


class CreateCatalogSessionPlanRequest(BaseModel):
    catalog_topic_id: str = Field(..., min_length=24, max_length=24)
    sequence_number: int = Field(..., ge=1, le=500)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    target_duration_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    teacher_notes: str = Field(default="", max_length=4000)


class UpdateClassSessionPlanRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    session_study_points: Optional[List[str]] = None
    session_learning_outcomes: Optional[List[str]] = None
    sequence_number: Optional[int] = Field(default=None, ge=1, le=500)
    target_duration_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    teacher_notes: Optional[str] = Field(default=None, max_length=4000)


class SetPlanItemsRequest(BaseModel):
    items: List[PlanItemIn]


class ClassSessionPlanOut(BaseModel):
    id: str
    plan_scope: str = "teacher"
    teacher_topic_id: Optional[str] = None
    catalog_topic_id: Optional[str] = None
    class_id: str
    subject_id: str
    sequence_number: int
    title: str
    description: str
    session_study_points: List[str] = Field(default_factory=list)
    session_learning_outcomes: List[str] = Field(default_factory=list)
    target_duration_minutes: Optional[int]
    teacher_notes: str
    curriculum_schema_version: str
    curriculum_revision: int
    status: str
    published_at: Optional[str]
    items: List[PlanItemOut]


class CreateClassSessionInstanceRequest(BaseModel):
    class_session_plan_id: str = Field(..., min_length=24, max_length=24)
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str = Field(default="UTC", max_length=64)
    co_teacher_ids: List[str] = Field(default_factory=list)


class RescheduleInstanceRequest(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: Optional[str] = Field(default=None, max_length=64)


class EnrollStudentsRequest(BaseModel):
    student_ids: List[str] = Field(default_factory=list)
    whole_class: bool = False


class UpdateEnrollmentRequest(BaseModel):
    enrollment_status: Literal["enrolled", "excused", "withdrawn"]


class ClassSessionInstanceOut(BaseModel):
    id: str
    class_session_plan_id: str
    teacher_topic_id: str
    class_id: str
    subject_id: str
    primary_teacher_id: str
    scheduled_start: str
    scheduled_end: str
    timezone: str
    status: str
    enrollment_count: int = 0
    plan_snapshot: dict


class EnrollmentOut(BaseModel):
    id: str
    class_session_instance_id: str
    student_id: str
    enrollment_status: str
    enrolled_at: str


def _item_out(item: ClassSessionPlanItem) -> PlanItemOut:
    return PlanItemOut(
        item_id=item.item_id,
        sort_order=item.sort_order,
        item_type=item.item_type,
        curriculum_zone_id=str(item.curriculum_zone_id) if item.curriculum_zone_id else None,
        curriculum_cluster_id=str(item.curriculum_cluster_id)
        if item.curriculum_cluster_id
        else None,
        curriculum_concept_id=str(item.curriculum_concept_id)
        if item.curriculum_concept_id
        else None,
        zone_number=item.zone_number,
        canonical_runtime_key_snapshot=item.canonical_runtime_key_snapshot,
        display_name_snapshot=item.display_name_snapshot,
        estimated_minutes=item.estimated_minutes,
        is_required=item.is_required,
        non_curriculum_label=item.non_curriculum_label,
    )


def plan_to_out(plan: ClassSessionPlan) -> ClassSessionPlanOut:
    return ClassSessionPlanOut(
        id=str(plan.id),
        plan_scope=getattr(plan, "plan_scope", "teacher") or "teacher",
        teacher_topic_id=str(plan.teacher_topic_id) if plan.teacher_topic_id else None,
        catalog_topic_id=str(plan.catalog_topic_id) if plan.catalog_topic_id else None,
        class_id=plan.class_id,
        subject_id=plan.subject_id,
        sequence_number=plan.sequence_number,
        title=plan.title,
        description=plan.description,
        session_study_points=list(getattr(plan, "session_study_points", None) or []),
        session_learning_outcomes=list(
            getattr(plan, "session_learning_outcomes", None) or []
        ),
        target_duration_minutes=plan.target_duration_minutes,
        teacher_notes=plan.teacher_notes,
        curriculum_schema_version=plan.curriculum_schema_version,
        curriculum_revision=plan.curriculum_revision,
        status=plan.status,
        published_at=plan.published_at.isoformat() if plan.published_at else None,
        items=[_item_out(i) for i in plan.items],
    )


def instance_to_out(
    inst: ClassSessionInstance, *, enrollment_count: int = 0
) -> ClassSessionInstanceOut:
    snap = inst.plan_snapshot
    return ClassSessionInstanceOut(
        id=str(inst.id),
        class_session_plan_id=str(inst.class_session_plan_id),
        teacher_topic_id=str(inst.teacher_topic_id),
        class_id=inst.class_id,
        subject_id=inst.subject_id,
        primary_teacher_id=str(inst.primary_teacher_id),
        scheduled_start=inst.scheduled_start.isoformat(),
        scheduled_end=inst.scheduled_end.isoformat(),
        timezone=inst.timezone,
        status=inst.status,
        enrollment_count=enrollment_count,
        plan_snapshot={
            "plan_id": str(snap.plan_id),
            "title": snap.title,
            "sequence_number": snap.sequence_number,
            "curriculum_revision": snap.curriculum_revision,
            "items": [_item_out(i).model_dump() for i in snap.items],
        },
    )


def enrollment_to_out(row: StudentPlanEnrollment) -> EnrollmentOut:
    return EnrollmentOut(
        id=str(row.id),
        class_session_instance_id=str(row.class_session_instance_id),
        student_id=str(row.student_id),
        enrollment_status=row.enrollment_status,
        enrolled_at=row.enrolled_at.isoformat(),
    )
