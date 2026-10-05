from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.curriculum.curriculum_enums import TopicSource

PlanProgressStatus = Literal["not_started", "in_progress", "completed"]


class ResumePointer(BaseModel):
    """Frozen resume coordinates — no curriculum re-resolution on restore."""

    session_plan_id: Optional[PydanticObjectId] = Field(default=None)
    cluster_index: int = Field(default=0, ge=0)
    concept_index: int = Field(default=0, ge=0)
    curriculum_cluster_id: Optional[PydanticObjectId] = Field(default=None)
    curriculum_concept_id: Optional[PydanticObjectId] = Field(default=None)
    current_concept: Optional[str] = Field(default=None, max_length=500)


class StudentPlanProgress(BaseDocument):
    """
    Multi-session plan progression for a student on a topic track.

    Completion unit = ClassSessionPlan (one planned session), not concept/zone.
    """

    student_id: PydanticObjectId = Field(...)
    organization_id: PydanticObjectId = Field(...)
    plan_track_key: str = Field(
        ...,
        min_length=8,
        max_length=200,
        description="Stable track id, e.g. catalog:{topic_id} or teacher:{topic_id}:{class_id}",
    )
    topic_id: PydanticObjectId = Field(...)
    topic_source: TopicSource = Field(default="catalog")
    plan_scope: TopicSource = Field(default="catalog")
    catalog_topic_id: Optional[PydanticObjectId] = Field(default=None)
    teacher_topic_id: Optional[PydanticObjectId] = Field(default=None)
    class_id: str = Field(default="", max_length=64)
    subject_id: str = Field(default="", max_length=64)

    current_session_plan_id: Optional[PydanticObjectId] = Field(default=None)
    current_cluster_id: Optional[PydanticObjectId] = Field(default=None)
    current_concept_id: Optional[PydanticObjectId] = Field(default=None)
    resume_pointer: ResumePointer = Field(default_factory=ResumePointer)

    completed_session_plan_ids: List[PydanticObjectId] = Field(default_factory=list)
    completed_cluster_ids: List[PydanticObjectId] = Field(default_factory=list)
    completed_clusters_by_session: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="session_plan_id -> curriculum_cluster_id strings completed",
    )
    unlocked_session_plan_ids: List[PydanticObjectId] = Field(default_factory=list)

    completion_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    status: PlanProgressStatus = Field(default="not_started")

    started_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)

    last_transition: Optional[Dict[str, Any]] = Field(
        default=None,
        description="QA-visible session transition banner payload",
    )

    class Settings:
        name = "student_plan_progress"
        indexes = [
            IndexModel(
                [("student_id", 1), ("plan_track_key", 1)],
                name="uq_student_plan_track",
                unique=True,
            ),
            IndexModel([("student_id", 1), ("topic_id", 1)]),
        ]
