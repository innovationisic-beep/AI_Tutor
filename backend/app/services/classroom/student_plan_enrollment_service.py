from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.classroom.student_plan_enrollment import StudentPlanEnrollment
from app.models.identification.student_profiles import StudentProfile
from app.models.identification.users import User
from app.repositories.student_plan_enrollment_repository import (
    StudentPlanEnrollmentRepository,
)
from app.services.classroom.class_session_instance_service import (
    ClassSessionInstanceService,
)


class StudentPlanEnrollmentService:
    def __init__(
        self,
        enrollment_repo: StudentPlanEnrollmentRepository | None = None,
        instance_service: ClassSessionInstanceService | None = None,
    ) -> None:
        self._enrollments = enrollment_repo or StudentPlanEnrollmentRepository()
        self._instances = instance_service or ClassSessionInstanceService()

    async def list_enrollments(
        self,
        instance_id: PydanticObjectId,
        user: User,
        *,
        enrollment_status: Optional[str] = None,
    ) -> List[StudentPlanEnrollment]:
        await self._instances.get(instance_id, user)
        return await self._enrollments.list_for_instance(
            instance_id, enrollment_status=enrollment_status
        )

    async def enroll_students(
        self,
        instance_id: PydanticObjectId,
        user: User,
        student_ids: List[PydanticObjectId],
    ) -> List[StudentPlanEnrollment]:
        inst = await self._instances.get(instance_id, user)
        if inst.status == "cancelled":
            raise HTTPException(status_code=409, detail="Cannot enroll on cancelled instance")
        if not student_ids:
            raise HTTPException(status_code=400, detail="student_ids required")
        out: List[StudentPlanEnrollment] = []
        for sid in student_ids:
            existing = await self._enrollments.get_one(
                {"class_session_instance_id": instance_id, "student_id": sid}
            )
            if existing is not None:
                if existing.enrollment_status == "withdrawn":
                    existing.enrollment_status = "enrolled"
                    existing.enrolled_at = datetime.utcnow()
                    existing.enrolled_by = user.id
                    await existing.save()
                    out.append(existing)
                else:
                    out.append(existing)
                continue
            row = await self._enrollments.create(
                {
                    "organization_id": inst.organization_id,
                    "class_session_instance_id": instance_id,
                    "student_id": sid,
                    "enrollment_status": "enrolled",
                    "enrolled_by": user.id,
                }
            )
            out.append(row)
        return out

    async def enroll_whole_class(
        self,
        instance_id: PydanticObjectId,
        user: User,
    ) -> List[StudentPlanEnrollment]:
        inst = await self._instances.get(instance_id, user)
        profiles = await StudentProfile.find(
            {
                "organization_id": inst.organization_id,
                "class_id": inst.class_id,
            }
        ).to_list()
        student_ids = [p.user_id for p in profiles if p.user_id is not None]
        if not student_ids:
            raise HTTPException(
                status_code=400,
                detail="No students found for this class",
            )
        return await self.enroll_students(instance_id, user, student_ids)

    async def update_status(
        self,
        instance_id: PydanticObjectId,
        student_id: PydanticObjectId,
        user: User,
        *,
        enrollment_status: str,
    ) -> StudentPlanEnrollment:
        await self._instances.get(instance_id, user)
        row = await self._enrollments.get_one(
            {"class_session_instance_id": instance_id, "student_id": student_id}
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        if enrollment_status not in ("enrolled", "excused", "withdrawn"):
            raise HTTPException(status_code=400, detail="Invalid enrollment_status")
        row.enrollment_status = enrollment_status  # type: ignore[assignment]
        await row.save()
        return row

    async def remove_enrollment(
        self,
        instance_id: PydanticObjectId,
        student_id: PydanticObjectId,
        user: User,
    ) -> None:
        await self._instances.get(instance_id, user)
        row = await self._enrollments.get_one(
            {"class_session_instance_id": instance_id, "student_id": student_id}
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        await row.delete()
