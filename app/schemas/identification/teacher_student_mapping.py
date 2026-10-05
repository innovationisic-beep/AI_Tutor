from beanie.odm.fields import PydanticObjectId

from .base import BaseSchema


class TeacherStudentMappingCreate(BaseSchema):
    organization_id: PydanticObjectId
    teacher_id: PydanticObjectId
    student_id: PydanticObjectId
