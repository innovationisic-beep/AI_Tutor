from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class TeacherStudentMapping(BaseDocument):
    """Many-to-many assignment between teachers and students per tenant."""

    organization_id: PydanticObjectId = Field(...)
    teacher_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    assigned_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "teacher_student_mapping"
        indexes = [
            IndexModel([("organization_id", 1), ("teacher_id", 1)]),
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel(
                [("organization_id", 1), ("teacher_id", 1), ("student_id", 1)],
                unique=True,
            ),
        ]
