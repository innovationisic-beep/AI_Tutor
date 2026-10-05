from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr, validator
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class VideoSubtitle(Document):
    """Subtitle chunk tied to a video timeline for AI explainability and retrieval."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    video_id: Indexed(PydanticObjectId) = Field(...)
    start_time: StrictFloat = Field(..., ge=0.0)
    end_time: StrictFloat = Field(..., ge=0.0)
    text: StrictStr = Field(..., min_length=1, max_length=5000)
    chunk_index: StrictInt = Field(..., ge=0)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    created_at: datetime = Field(default_factory=utc_now)

    @validator("end_time")
    def validate_time_window(cls, value: StrictFloat, values: dict) -> StrictFloat:
        start_time = values.get("start_time")
        if start_time is not None and value < start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return value

    class Settings:
        name = "video_subtitles"
        indexes = [
            IndexModel([("organization_id", 1), ("video_id", 1)]),
            IndexModel(
                [("organization_id", 1), ("video_id", 1), ("chunk_index", 1)],
                unique=True,
            ),
        ]
