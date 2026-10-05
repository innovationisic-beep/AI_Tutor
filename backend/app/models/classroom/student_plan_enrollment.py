from __future__ import annotations

from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.classroom.classroom_enums import EnrollmentStatus


class StudentPlanEnrollment(BaseDocument):
    """Student roster entry for a class session instance."""

    organization_id: PydanticObjectId = Field(...)
    class_session_instance_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    enrollment_status: EnrollmentStatus = Field(default="enrolled")
    enrolled_at: datetime = Field(default_factory=datetime.utcnow)
    enrolled_by: PydanticObjectId = Field(...)

    class Settings:
        name = "student_plan_enrollments"
        indexes = [
            IndexModel(
                [("class_session_instance_id", 1), ("student_id", 1)],
                unique=True,
            ),
            IndexModel([("student_id", 1), ("enrollment_status", 1)]),
        ]
