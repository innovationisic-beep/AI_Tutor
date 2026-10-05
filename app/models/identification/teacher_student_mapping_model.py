from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class TeacherStudentMapping(Document):
    """Many-to-many assignment between teachers and students per tenant."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    teacher_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    assigned_at: datetime = Field(default_factory=utc_now)

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
