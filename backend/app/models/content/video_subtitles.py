from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class VideoSubtitle(BaseDocument):
    """Subtitle chunk tied to a video timeline for AI explainability and retrieval."""

    organization_id: PydanticObjectId = Field(...)
    video_id: PydanticObjectId = Field(...)
    start_time: float = Field(..., ge=0.0)
    end_time: float = Field(..., ge=0.0)
    text: str = Field(..., min_length=1, max_length=5000)
    chunk_index: int = Field(..., ge=0)
    embedding_vector: Optional[List[float]] = Field(default=None, max_length=4096)

    class Settings:
        name = "video_subtitles"
        indexes = [
            IndexModel([("organization_id", 1), ("video_id", 1)]),
            IndexModel(
                [("organization_id", 1), ("video_id", 1), ("chunk_index", 1)],
                unique=True,
            ),
        ]
