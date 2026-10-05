from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr

from app.schemas.identification.base import BaseSchema


class PerformanceMetricsCreate(BaseSchema):
    """Request schema for creating monthly performance metrics."""

    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    month: StrictStr = Field(..., min_length=7, max_length=7)
    avg_mastery: StrictFloat = Field(..., ge=0.0, le=1.0)
    learning_time_minutes: StrictInt = Field(..., ge=0)
    retention_score: StrictFloat = Field(..., ge=0.0, le=1.0)
    improvement_rate: StrictFloat = Field(..., ge=-1.0, le=1.0)
    topics_completed: StrictInt = Field(..., ge=0)
    confusion_frequency: StrictFloat = Field(..., ge=0.0)


class PerformanceMetricsRead(BaseSchema):
    """Response schema for monthly performance metrics."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    student_id: PydanticObjectId
    month: StrictStr
    avg_mastery: StrictFloat
    learning_time_minutes: StrictInt
    retention_score: StrictFloat
    improvement_rate: StrictFloat
    topics_completed: StrictInt
    confusion_frequency: StrictFloat
    updated_at: datetime


class PerformanceMetricsUpdate(BaseSchema):
    """Request schema for updating monthly performance metrics."""

    avg_mastery: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    learning_time_minutes: StrictInt | None = Field(default=None, ge=0)
    retention_score: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    improvement_rate: StrictFloat | None = Field(default=None, ge=-1.0, le=1.0)
    topics_completed: StrictInt | None = Field(default=None, ge=0)
    confusion_frequency: StrictFloat | None = Field(default=None, ge=0.0)
