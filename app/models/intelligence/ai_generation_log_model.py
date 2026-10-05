from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.intelligence_enums import AITaskType
from app.utils.timestamps import utc_now


class AIGenerationLog(Document):
    """Token and latency audit log for LLM generations."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: PydanticObjectId | None = Field(default=None)
    session_id: PydanticObjectId | None = Field(default=None)
    model_used: Indexed(StrictStr) = Field(..., min_length=2, max_length=80)
    task_type: AITaskType = Field(...)
    tokens_used: StrictInt = Field(..., ge=0)
    estimated_cost: StrictFloat = Field(..., ge=0.0)
    response_time_ms: StrictInt = Field(..., ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "ai_generation_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("model_used", 1)]),
        ]
