"""Topic-level curriculum tree, validation, and publish (Phase 1)."""

from __future__ import annotations

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas.curriculum_structure import (
    CurriculumPublishOut,
    CurriculumTreeOut,
    CurriculumValidationOut,
)
from app.core.dependencies import get_current_teacher_or_admin
from app.models.identification.users import User
from app.services.curriculum.curriculum_publish_service import CurriculumPublishService
from app.services.curriculum.curriculum_tree_service import CurriculumTreeService
from app.services.curriculum.curriculum_validation_service import (
    CurriculumValidationService,
)
from app.services.curriculum.topic_context_service import resolve_topic_context

router = APIRouter(tags=["Topic curriculum"])


def _oid(value: str, *, label: str = "id") -> PydanticObjectId:
    try:
        return PydanticObjectId(value.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label}",
        ) from exc


@router.get("/topics/{topic_id}/curriculum", response_model=CurriculumTreeOut)
async def get_topic_curriculum_tree(
    topic_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    ctx = await resolve_topic_context(
        _oid(topic_id, label="topic_id"),
        topic_source,
        current_user,
        require_mutation_access=False,
    )
    return await CurriculumTreeService().get_tree(ctx)


@router.get(
    "/topics/{topic_id}/curriculum/validate",
    response_model=CurriculumValidationOut,
)
async def validate_topic_curriculum(
    topic_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    ctx = await resolve_topic_context(
        _oid(topic_id, label="topic_id"),
        topic_source,
        current_user,
        require_mutation_access=False,
    )
    result = await CurriculumValidationService().validate(ctx)
    return result.to_dict()


@router.post(
    "/topics/{topic_id}/curriculum/publish",
    response_model=CurriculumPublishOut,
)
async def publish_topic_curriculum(
    topic_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    ctx = await resolve_topic_context(
        _oid(topic_id, label="topic_id"),
        topic_source,
        current_user,
    )
    return await CurriculumPublishService().publish(ctx)


@router.post(
    "/topics/{topic_id}/curriculum/unpublish",
    response_model=CurriculumPublishOut,
)
async def unpublish_topic_curriculum(
    topic_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    ctx = await resolve_topic_context(
        _oid(topic_id, label="topic_id"),
        topic_source,
        current_user,
    )
    return await CurriculumPublishService().unpublish(ctx)
