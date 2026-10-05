from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr
from pymongo import IndexModel

from app.enums.content_enums import ApprovalStatus, ContentType
from app.utils.timestamps import utc_now


class ContentApprovalQueue(Document):
    """Moderation queue item for content approval workflows."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    content_type: ContentType = Field(...)
    content_id: Indexed(PydanticObjectId) = Field(...)
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    status: ApprovalStatus = Field(default=ApprovalStatus.pending)
    reviewed_by_teacher_id: PydanticObjectId | None = Field(default=None)
    review_notes: StrictStr | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_at: datetime | None = Field(default=None)

    class Settings:
        name = "content_approval_queue"
        indexes = [
            IndexModel([("organization_id", 1), ("status", 1)]),
        ]
