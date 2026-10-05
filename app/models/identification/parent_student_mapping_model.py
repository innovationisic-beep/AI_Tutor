from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.enums.user_enums import RelationshipType
from app.utils.timestamps import utc_now


class ParentStudentMapping(Document):
    """Many-to-many mapping of parents and students within one organization."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    parent_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    relationship_type: RelationshipType = Field(...)
    created_at: datetime = Field(default_factory=utc_now)

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
