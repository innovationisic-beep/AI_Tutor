from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictInt, StrictStr

from app.enums.content_enums import VideoStatus
from app.schemas.identification.base import BaseSchema


class VideoCreate(BaseSchema):
    """Request schema for creating video metadata."""

    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    title: StrictStr = Field(..., min_length=2, max_length=200)
    description: StrictStr = Field(..., min_length=3, max_length=4000)
    video_url: StrictStr = Field(..., min_length=8, max_length=2000)
    thumbnail_url: StrictStr | None = Field(default=None, min_length=8, max_length=2000)
    duration_seconds: StrictInt = Field(..., ge=0)
    grade: StrictStr = Field(..., min_length=1, max_length=32)
    board: StrictStr = Field(..., min_length=1, max_length=64)
    status: VideoStatus = Field(default=VideoStatus.draft)
    uploaded_by_teacher_id: PydanticObjectId
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)


class VideoRead(BaseSchema):
    """Response schema for video resources."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    topic_id: PydanticObjectId
    title: StrictStr
    description: StrictStr
    video_url: StrictStr
    thumbnail_url: StrictStr | None
    duration_seconds: StrictInt
    grade: StrictStr
    board: StrictStr
    status: VideoStatus
    uploaded_by_teacher_id: PydanticObjectId
    embedding_vector: list[StrictFloat] | None
    created_at: datetime


class VideoUpdate(BaseSchema):
    """Request schema for updating video metadata."""

    title: StrictStr | None = Field(default=None, min_length=2, max_length=200)
    description: StrictStr | None = Field(default=None, min_length=3, max_length=4000)
    video_url: StrictStr | None = Field(default=None, min_length=8, max_length=2000)
    thumbnail_url: StrictStr | None = Field(default=None, min_length=8, max_length=2000)
    duration_seconds: StrictInt | None = Field(default=None, ge=0)
    grade: StrictStr | None = Field(default=None, min_length=1, max_length=32)
    board: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    status: VideoStatus | None = None
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
