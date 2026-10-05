from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class AIGenerationLog(BaseDocument):
    """Token and latency audit log for LLM generations."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: Optional[PydanticObjectId] = Field(default=None)
    session_id: Optional[PydanticObjectId] = Field(default=None)
    model_used: str = Field(..., min_length=2, max_length=80)
    task_type: Literal[
        "explanation",
        "teachback_evaluation",
        "quiz_generation",
        "note_generation",
        "recommendation_reasoning",
        "qa",
    ] = Field(...)
    tokens_used: int = Field(..., ge=0)
    estimated_cost: float = Field(..., ge=0.0)
    response_time_ms: int = Field(..., ge=0)

    class Settings:
        name = "ai_generation_logs"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("model_used", 1)]),
        ]
