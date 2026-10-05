from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.classroom.class_session_plan import ClassSessionPlanItem
from app.models.classroom.classroom_enums import ClassSessionInstanceStatus


class ClassSessionPlanSnapshot(BaseModel):
    """Frozen plan coverage copied at instance creation."""

    plan_id: PydanticObjectId
    title: str
    sequence_number: int
    curriculum_revision: int
    items: List[ClassSessionPlanItem] = Field(default_factory=list)


class ClassSessionInstance(BaseDocument):
    """Scheduled occurrence of a published class session plan."""

    organization_id: PydanticObjectId = Field(...)
    class_session_plan_id: PydanticObjectId = Field(...)
    teacher_topic_id: PydanticObjectId = Field(...)
    class_id: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=64)
    primary_teacher_id: PydanticObjectId = Field(...)
    co_teacher_ids: List[PydanticObjectId] = Field(default_factory=list)
    scheduled_start: datetime = Field(...)
    scheduled_end: datetime = Field(...)
    timezone: str = Field(default="UTC", max_length=64)
    plan_snapshot: ClassSessionPlanSnapshot
    status: ClassSessionInstanceStatus = Field(default="scheduled")
    actual_start: Optional[datetime] = Field(default=None)
    actual_end: Optional[datetime] = Field(default=None)

    class Settings:
        name = "class_session_instances"
        indexes = [
            IndexModel(
                [("organization_id", 1), ("class_id", 1), ("scheduled_start", 1)]
            ),
            IndexModel([("class_session_plan_id", 1)]),
            IndexModel(
                [
                    ("organization_id", 1),
                    ("primary_teacher_id", 1),
                    ("status", 1),
                    ("scheduled_start", 1),
                ]
            ),
        ]
