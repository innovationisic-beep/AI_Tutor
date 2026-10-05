from datetime import date, datetime
from typing import Any

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictInt
from pymongo import IndexModel

from app.enums.intelligence_enums import PlanGenerator
from app.utils.timestamps import utc_now


class LearningPlan(Document):
    """Weekly and daily adaptive roadmap for a student."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    week_start_date: date = Field(...)
    weekly_roadmap: list[dict[str, Any]] = Field(default_factory=list)
    daily_plan: dict[str, Any] = Field(default_factory=dict)
    revision_schedule: dict[str, Any] = Field(default_factory=dict)
    generated_by: PlanGenerator = Field(default=PlanGenerator.ai)
    plan_version: StrictInt = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "learning_plans"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("week_start_date", 1)]),
        ]
