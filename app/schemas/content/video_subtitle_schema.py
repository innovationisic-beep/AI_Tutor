from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr, validator

from app.schemas.identification.base import BaseSchema


class VideoSubtitleCreate(BaseSchema):
    """Request schema for creating a subtitle chunk."""

    organization_id: PydanticObjectId
    video_id: PydanticObjectId
    start_time: StrictFloat = Field(..., ge=0.0)
    end_time: StrictFloat = Field(..., ge=0.0)
    text: StrictStr = Field(..., min_length=1, max_length=5000)
    chunk_index: StrictInt = Field(..., ge=0)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)

    @validator("end_time")
    def validate_time_window(cls, value: StrictFloat, values: dict) -> StrictFloat:
        start_time = values.get("start_time")
        if start_time is not None and value < start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return value


class VideoSubtitleRead(BaseSchema):
    """Response schema for subtitle chunks."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    video_id: PydanticObjectId
    start_time: StrictFloat
    end_time: StrictFloat
    text: StrictStr
    chunk_index: StrictInt
    embedding_vector: list[StrictFloat] | None
    created_at: datetime


class VideoSubtitleUpdate(BaseSchema):
    """Request schema for updating subtitle chunks."""

    start_time: StrictFloat | None = Field(default=None, ge=0.0)
    end_time: StrictFloat | None = Field(default=None, ge=0.0)
    text: StrictStr | None = Field(default=None, min_length=1, max_length=5000)
    chunk_index: StrictInt | None = Field(default=None, ge=0)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
