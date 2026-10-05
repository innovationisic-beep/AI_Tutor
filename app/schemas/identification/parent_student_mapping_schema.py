from datetime import datetime

from beanie.odm.fields import PydanticObjectId

from app.enums.user_enums import RelationshipType
from app.schemas.identification.base import BaseSchema


class ParentStudentMappingCreate(BaseSchema):
    """Request schema for linking parents to students."""

    organization_id: PydanticObjectId
    parent_id: PydanticObjectId
    student_id: PydanticObjectId
    relationship_type: RelationshipType


class ParentStudentMappingRead(BaseSchema):
    """Response schema for parent-student mappings."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    parent_id: PydanticObjectId
    student_id: PydanticObjectId
    relationship_type: RelationshipType
    created_at: datetime
