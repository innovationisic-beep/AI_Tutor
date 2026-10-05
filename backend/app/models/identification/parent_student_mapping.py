from typing import Literal

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class ParentStudentMapping(BaseDocument):
    """Many-to-many mapping of parents and students within one organization."""

    organization_id: PydanticObjectId = Field(...)
    parent_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    relationship_type: Literal["mother", "father", "guardian"] = Field(...)

    class Settings:
        name = "parent_student_mapping"
        indexes = [
            IndexModel([("organization_id", 1), ("parent_id", 1)]),
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel(
                [("organization_id", 1), ("parent_id", 1), ("student_id", 1)],
                unique=True,
            ),
        ]
