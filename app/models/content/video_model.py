from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr
from pymongo import IndexModel

from app.enums.content_enums import VideoStatus
from app.utils.timestamps import utc_now


class Video(Document):
    """Metadata record for educational videos stored in external media infrastructure."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    title: StrictStr = Field(..., min_length=2, max_length=200)
    description: StrictStr = Field(..., min_length=3, max_length=4000)
    video_url: StrictStr = Field(..., min_length=8, max_length=2000)
    thumbnail_url: StrictStr | None = Field(default=None, min_length=8, max_length=2000)
    duration_seconds: StrictInt = Field(..., ge=0)
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    status: VideoStatus = Field(default=VideoStatus.draft)
    uploaded_by_teacher_id: Indexed(PydanticObjectId) = Field(...)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "videos"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
