from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.schemas.identification.base import BaseSchema


class TopicQuestionBankCreate(BaseSchema):
    """Request schema for creating question bank entries."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    difficulty_level: StrictInt = Field(..., ge=1, le=5)
    question_text: StrictStr = Field(..., min_length=3, max_length=5000)
    options: list[StrictStr] = Field(..., min_items=2, max_items=10)
    correct_answer: StrictStr = Field(..., min_length=1, max_length=2000)
    explanation: StrictStr = Field(..., min_length=1, max_length=5000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    approved: StrictBool = Field(default=False)
    usage_count: StrictInt = Field(default=0, ge=0)


class TopicQuestionBankRead(BaseSchema):
    """Response schema for question bank entries."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    difficulty_level: StrictInt
    question_text: StrictStr
    options: list[StrictStr]
    correct_answer: StrictStr
    explanation: StrictStr
    embedding_vector: list[StrictFloat] | None
    approved: StrictBool
    usage_count: StrictInt
    created_at: datetime


class TopicQuestionBankUpdate(BaseSchema):
    """Request schema for updating question bank entries."""

    difficulty_level: StrictInt | None = Field(default=None, ge=1, le=5)
    question_text: StrictStr | None = Field(default=None, min_length=3, max_length=5000)
    options: list[StrictStr] | None = Field(default=None, min_items=2, max_items=10)
    correct_answer: StrictStr | None = Field(default=None, min_length=1, max_length=2000)
    explanation: StrictStr | None = Field(default=None, min_length=1, max_length=5000)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    approved: StrictBool | None = None
    usage_count: StrictInt | None = Field(default=None, ge=0)
