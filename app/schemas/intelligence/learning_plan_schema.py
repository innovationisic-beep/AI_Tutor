from datetime import date, datetime
from typing import Any

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictInt

from app.enums.intelligence_enums import PlanGenerator
from app.schemas.identification.base import BaseSchema


class LearningPlanCreate(BaseSchema):
    """Request schema for creating a learning plan."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    week_start_date: date
    weekly_roadmap: list[dict[str, Any]] = Field(default_factory=list)
    daily_plan: dict[str, Any] = Field(default_factory=dict)
    revision_schedule: dict[str, Any] = Field(default_factory=dict)
    generated_by: PlanGenerator = Field(default=PlanGenerator.ai)
    plan_version: StrictInt = Field(default=1, ge=1)


class LearningPlanRead(BaseSchema):
    """Response schema for learning plans."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    week_start_date: date
    weekly_roadmap: list[dict[str, Any]]
    daily_plan: dict[str, Any]
    revision_schedule: dict[str, Any]
    generated_by: PlanGenerator
    plan_version: StrictInt
    created_at: datetime
    updated_at: datetime


class LearningPlanUpdate(BaseSchema):
    """Request schema for updating a learning plan."""

    weekly_roadmap: list[dict[str, Any]] | None = None
    daily_plan: dict[str, Any] | None = None
    revision_schedule: dict[str, Any] | None = None
    generated_by: PlanGenerator | None = None
    plan_version: StrictInt | None = Field(default=None, ge=1)
