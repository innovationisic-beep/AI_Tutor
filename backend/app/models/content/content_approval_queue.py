from datetime import datetime
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class ContentApprovalQueue(BaseDocument):
    """Moderation queue item for content approval workflows."""

    organization_id: PydanticObjectId = Field(...)
    content_type: Literal["video", "note", "question"] = Field(...)
    content_id: PydanticObjectId = Field(...)
    embedding_vector: Optional[List[float]] = Field(default=None, max_length=4096)
    status: Literal["pending", "approved", "rejected"] = Field(default="pending")
    reviewed_by_teacher_id: Optional[PydanticObjectId] = Field(default=None)
    review_notes: Optional[str] = Field(default=None, max_length=2000)
    reviewed_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "content_approval_queue"
        indexes = [
            IndexModel([("organization_id", 1), ("status", 1)]),
        ]
