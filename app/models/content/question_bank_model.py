from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class TopicQuestionBank(Document):
    """Reusable question bank item scoped to topic and tenant."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    difficulty_level: StrictInt = Field(..., ge=1, le=5)
    question_text: StrictStr = Field(..., min_length=3, max_length=5000)
    options: list[StrictStr] = Field(..., min_items=2, max_items=10)
    correct_answer: StrictStr = Field(..., min_length=1, max_length=2000)
    explanation: StrictStr = Field(..., min_length=1, max_length=5000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    approved: StrictBool = Field(default=False)
    usage_count: StrictInt = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "topic_question_bank"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
