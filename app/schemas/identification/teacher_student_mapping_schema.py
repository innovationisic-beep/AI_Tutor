from datetime import datetime

from beanie.odm.fields import PydanticObjectId

from app.schemas.identification.base import BaseSchema


class TeacherStudentMappingCreate(BaseSchema):
    """Request schema for assigning teachers to students."""

    organization_id: PydanticObjectId
    teacher_id: PydanticObjectId
    student_id: PydanticObjectId


class TeacherStudentMappingRead(BaseSchema):
    """Response schema for teacher-student mappings."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    teacher_id: PydanticObjectId
    student_id: PydanticObjectId
    assigned_at: datetime
