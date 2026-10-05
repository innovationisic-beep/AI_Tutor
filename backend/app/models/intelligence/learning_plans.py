from datetime import date
from typing import Any, Dict, List, Literal

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class LearningPlan(BaseDocument):
    """Weekly and daily adaptive roadmap for a student."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    week_start_date: date = Field(...)
    weekly_roadmap: List[Dict[str, Any]] = Field(default_factory=list)
    daily_plan: Dict[str, Any] = Field(default_factory=dict)
    revision_schedule: Dict[str, Any] = Field(default_factory=dict)
    generated_by: Literal["ai", "teacher"] = Field(default="ai")
    plan_version: int = Field(default=1, ge=1)

    class Settings:
        name = "learning_plans"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("week_start_date", 1)]),
        ]
