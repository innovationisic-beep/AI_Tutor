from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class PerformanceMetrics(Document):
    """Monthly aggregated analytics for student learning progress."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    month: StrictStr = Field(..., min_length=7, max_length=7)
    avg_mastery: StrictFloat = Field(..., ge=0.0, le=1.0)
    learning_time_minutes: StrictInt = Field(..., ge=0)
    retention_score: StrictFloat = Field(..., ge=0.0, le=1.0)
    improvement_rate: StrictFloat = Field(..., ge=-1.0, le=1.0)
    topics_completed: StrictInt = Field(..., ge=0)
    confusion_frequency: StrictFloat = Field(..., ge=0.0)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "performance_metrics"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("month", 1)]),
        ]
