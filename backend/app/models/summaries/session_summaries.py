from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class SessionSummary(BaseDocument):
    """AI-generated summary for a learning session."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    session_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    summary_text: str = Field(..., min_length=1, max_length=2000)
    key_points_learned: List[str] = Field(default_factory=list, max_length=50)
    mistakes_identified: List[str] = Field(default_factory=list, max_length=50)
    strengths_identified: List[str] = Field(default_factory=list, max_length=50)
    ai_model_used: str = Field(..., min_length=2, max_length=80)
    tokens_used: Optional[int] = Field(default=None, ge=0)
    generation_time_ms: Optional[int] = Field(default=None, ge=0)

    class Settings:
        name = "session_summaries"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("session_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
