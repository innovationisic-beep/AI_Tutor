from __future__ import annotations

from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.student_plan_enrollment import StudentPlanEnrollment
from app.repositories.base_repository import BaseRepository


class StudentPlanEnrollmentRepository(BaseRepository[StudentPlanEnrollment]):
    def __init__(self) -> None:
        super().__init__(StudentPlanEnrollment)

    async def list_for_student(
        self,
        student_id: PydanticObjectId,
        *,
        enrollment_status: Optional[str] = "enrolled",
        limit: int = 200,
    ) -> List[StudentPlanEnrollment]:
        filters: dict = {"student_id": student_id}
        if enrollment_status:
            filters["enrollment_status"] = enrollment_status
        return await self.model.find(filters).sort("-enrolled_at").limit(limit).to_list()

    async def list_for_instance(
        self,
        instance_id: PydanticObjectId,
        *,
        enrollment_status: Optional[str] = None,
        limit: int = 500,
    ) -> List[StudentPlanEnrollment]:
        filters: dict = {"class_session_instance_id": instance_id}
        if enrollment_status:
            filters["enrollment_status"] = enrollment_status
        return await self.model.find(filters).sort("+enrolled_at").limit(limit).to_list()

    async def count_for_instance(self, instance_id: PydanticObjectId) -> int:
        return await self.model.find(
            {"class_session_instance_id": instance_id}
        ).count()


def get_student_plan_enrollment_repository() -> StudentPlanEnrollmentRepository:
    return StudentPlanEnrollmentRepository()
