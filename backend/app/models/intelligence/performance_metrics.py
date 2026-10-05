from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class PerformanceMetric(BaseDocument):
    """Monthly aggregated analytics for student learning progress."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    month: str = Field(..., min_length=7, max_length=7)
    avg_mastery: float = Field(..., ge=0.0, le=1.0)
    learning_time_minutes: int = Field(..., ge=0)
    retention_score: float = Field(..., ge=0.0, le=1.0)
    improvement_rate: float = Field(..., ge=-1.0, le=1.0)
    topics_completed: int = Field(..., ge=0)
    confusion_frequency: float = Field(..., ge=0.0)

    class Settings:
        name = "performance_metrics"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("month", 1)]),
        ]
