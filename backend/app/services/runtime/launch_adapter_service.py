"""Orchestrate classroom session launch into SessionService."""

from __future__ import annotations

from typing import Any, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.classroom.class_session_instance import ClassSessionInstance
from app.models.identification.users import User
from app.models.teacher_topic import TeacherTopic
from app.repositories.class_session_instance_repository import (
    ClassSessionInstanceRepository,
)
from app.repositories.session_repository import SessionRepository
from app.repositories.student_plan_enrollment_repository import (
    StudentPlanEnrollmentRepository,
)
from app.repositories.topic_repository import TopicRepository
from app.services.runtime.curriculum_resolution_service import (
    CurriculumResolutionError,
    CurriculumResolutionService,
)
from app.services.session_service import SessionService


class LaunchAdapterService:
    def __init__(
        self,
        *,
        instance_repo: ClassSessionInstanceRepository | None = None,
        enrollment_repo: StudentPlanEnrollmentRepository | None = None,
        resolver: CurriculumResolutionService | None = None,
        session_repo: SessionRepository | None = None,
        topic_repo: TopicRepository | None = None,
    ) -> None:
        self._instances = instance_repo or ClassSessionInstanceRepository()
        self._enrollments = enrollment_repo or StudentPlanEnrollmentRepository()
        self._resolver = resolver or CurriculumResolutionService()
        self._session_repo = session_repo or SessionRepository()
        self._topic_repo = topic_repo or TopicRepository()

    async def launch_class_session(
        self,
        student: User,
        *,
        class_session_instance_id: PydanticObjectId,
        action: Optional[Literal["continue", "restart"]] = None,
    ) -> dict[str, Any]:
        if student.role != "student":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student access required",
            )
        if student.organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization required",
            )

        instance = await self._instances.get_by_id(class_session_instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="Instance not found")
        if instance.organization_id != student.organization_id:
            raise HTTPException(status_code=403, detail="Not in your organization")

        enrollment = await self._enrollments.get_one(
            {
                "class_session_instance_id": class_session_instance_id,
                "student_id": student.id,
            }
        )
        if enrollment is None or enrollment.enrollment_status != "enrolled":
            raise HTTPException(status_code=403, detail="NOT_ENROLLED")

        tt = await TeacherTopic.get(instance.teacher_topic_id)
        if tt is None:
            raise HTTPException(status_code=404, detail="Teacher topic not found")
        if tt.curriculum_schema_version != "v2":
            raise HTTPException(status_code=400, detail="V2_REQUIRED")
        if not tt.supports_class_sessions:
            raise HTTPException(
                status_code=400,
                detail="supports_class_sessions is not enabled for this topic",
            )

        try:
            manifest = self._resolver.resolve_class_session(instance)
        except CurriculumResolutionError as exc:
            status_code = (
                status.HTTP_409_CONFLICT
                if exc.code == "INSTANCE_NOT_LAUNCHABLE"
                else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(status_code=status_code, detail=exc.code) from exc

        service = SessionService(self._session_repo, self._topic_repo)
        try:
            out = await service.start_session(
                student.id,
                instance.teacher_topic_id,
                action=action,
                curriculum_class_id=instance.class_id,
                curriculum_subject_id=instance.subject_id,
                student_organization_id=student.organization_id,
                runtime_curriculum_manifest=manifest,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if isinstance(out, dict):
            return {
                "type": out.get("type", "resume_prompt"),
                "message": out.get("message"),
                "buttons": out.get("buttons"),
                "session_id": out.get("session_id"),
                "manifest_summary": self._manifest_summary(manifest),
            }

        return {
            "type": "session",
            "session_id": str(out.id),
            "manifest_summary": self._manifest_summary(manifest),
        }

    @staticmethod
    def _manifest_summary(manifest) -> dict[str, Any]:
        keys = manifest.key_concepts
        return {
            "key_count": len(keys),
            "cluster_count": len(manifest.concept_clusters or []),
            "first_concept": keys[0] if keys else None,
            "launch_context": manifest.launch_context.model_dump(mode="json"),
        }
