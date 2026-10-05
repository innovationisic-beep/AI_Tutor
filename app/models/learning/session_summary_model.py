from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictInt, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class SessionSummary(Document):
    """AI-generated summary for a learning session."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    session_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)

    summary_text: StrictStr = Field(..., min_length=1, max_length=2000)
    key_points_learned: list[StrictStr] = Field(default_factory=list, max_items=50)
    mistakes_identified: list[StrictStr] = Field(default_factory=list, max_items=50)
    strengths_identified: list[StrictStr] = Field(default_factory=list, max_items=50)

    ai_model_used: StrictStr = Field(..., min_length=2, max_length=80)
    tokens_used: StrictInt | None = Field(default=None, ge=0)
    generation_time_ms: StrictInt | None = Field(default=None, ge=0)

    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "session_summaries"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1)]),
            IndexModel([("organization_id", 1), ("session_id", 1)]),
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
