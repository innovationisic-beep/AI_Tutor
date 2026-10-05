from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Video(BaseDocument):
    """Metadata record for educational videos stored in external media infrastructure."""

    organization_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=3, max_length=4000)
    video_url: str = Field(..., min_length=8, max_length=2000)
    thumbnail_url: Optional[str] = Field(default=None, min_length=8, max_length=2000)
    duration_seconds: int = Field(..., ge=0)
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(..., min_length=1, max_length=64)
    status: Literal["draft", "approved", "archived"] = Field(default="draft")
    uploaded_by_teacher_id: PydanticObjectId = Field(...)
    embedding_vector: Optional[List[float]] = Field(default=None, max_length=4096)

    class Settings:
        name = "videos"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
