from beanie.odm.fields import PydanticObjectId

from app.models.enums import RelationshipType

from .base import BaseSchema


class ParentStudentMappingCreate(BaseSchema):
    organization_id: PydanticObjectId
    parent_id: PydanticObjectId
    student_id: PydanticObjectId
    relationship_type: RelationshipType
