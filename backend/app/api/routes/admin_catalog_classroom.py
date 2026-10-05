"""Admin catalog session planning routes (Phase 3B.1B)."""

from __future__ import annotations

from typing import Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.routes.classroom import _items_from_request, _oid
from app.api.schemas.classroom import (
    ClassSessionPlanOut,
    CreateCatalogSessionPlanRequest,
    SetPlanItemsRequest,
    UpdateClassSessionPlanRequest,
    plan_to_out,
)
from app.core.dependencies import get_current_admin
from app.models.identification.users import User
from app.services.classroom.class_session_plan_service import ClassSessionPlanService

router = APIRouter(prefix="/admin/catalog/classroom", tags=["Admin catalog planning"])


@router.post("/plans", status_code=status.HTTP_201_CREATED, response_model=ClassSessionPlanOut)
async def create_catalog_session_plan(
    body: CreateCatalogSessionPlanRequest,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().create_catalog_draft(
        current_user,
        catalog_topic_id=_oid(body.catalog_topic_id, label="catalog_topic_id"),
        sequence_number=body.sequence_number,
        title=body.title,
        description=body.description,
        target_duration_minutes=body.target_duration_minutes,
        teacher_notes=body.teacher_notes,
    )
    return plan_to_out(plan)


@router.get("/plans", response_model=list[ClassSessionPlanOut])
async def list_catalog_session_plans(
    catalog_topic_id: str,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
) -> list[ClassSessionPlanOut]:
    plans = await ClassSessionPlanService().list_catalog_plans(
        current_user,
        catalog_topic_id=_oid(catalog_topic_id, label="catalog_topic_id"),
        status=status,
    )
    return [plan_to_out(p) for p in plans]


@router.get("/plans/{plan_id}", response_model=ClassSessionPlanOut)
async def get_catalog_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().get(_oid(plan_id, label="plan_id"), current_user)
    if plan.plan_scope != "catalog":
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan_to_out(plan)


@router.patch("/plans/{plan_id}", response_model=ClassSessionPlanOut)
async def update_catalog_session_plan(
    plan_id: str,
    body: UpdateClassSessionPlanRequest,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().update_draft(
        _oid(plan_id, label="plan_id"),
        current_user,
        title=body.title,
        description=body.description,
        session_study_points=body.session_study_points,
        session_learning_outcomes=body.session_learning_outcomes,
        sequence_number=body.sequence_number,
        target_duration_minutes=body.target_duration_minutes,
        teacher_notes=body.teacher_notes,
    )
    return plan_to_out(plan)


@router.put("/plans/{plan_id}/items", response_model=ClassSessionPlanOut)
async def set_catalog_plan_items(
    plan_id: str,
    body: SetPlanItemsRequest,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().set_items(
        _oid(plan_id, label="plan_id"),
        current_user,
        _items_from_request(body),
    )
    return plan_to_out(plan)


@router.post("/plans/{plan_id}/validate")
async def validate_catalog_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_admin),
) -> dict:
    return await ClassSessionPlanService().validate(
        _oid(plan_id, label="plan_id"),
        current_user,
    )


@router.post("/plans/{plan_id}/publish", response_model=ClassSessionPlanOut)
async def publish_catalog_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().publish(
        _oid(plan_id, label="plan_id"),
        current_user,
    )
    return plan_to_out(plan)


@router.post("/plans/{plan_id}/unpublish", response_model=ClassSessionPlanOut)
async def unpublish_catalog_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_admin),
) -> ClassSessionPlanOut:
    plan = await ClassSessionPlanService().unpublish(
        _oid(plan_id, label="plan_id"),
        current_user,
    )
    return plan_to_out(plan)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def archive_catalog_session_plan(
    plan_id: str,
    current_user: User = Depends(get_current_admin),
) -> Response:
    await ClassSessionPlanService().archive(_oid(plan_id, label="plan_id"), current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
