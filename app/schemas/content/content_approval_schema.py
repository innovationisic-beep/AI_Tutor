from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictFloat, StrictStr

from app.enums.content_enums import ApprovalStatus, ContentType
from app.schemas.identification.base import BaseSchema


class ContentApprovalQueueCreate(BaseSchema):
    """Request schema for enqueuing content moderation items."""

    organization_id: PydanticObjectId
    content_type: ContentType
    content_id: PydanticObjectId
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
    status: ApprovalStatus = Field(default=ApprovalStatus.pending)
    reviewed_by_teacher_id: PydanticObjectId | None = None
    review_notes: StrictStr | None = Field(default=None, max_length=2000)
    reviewed_at: datetime | None = None


class ContentApprovalQueueRead(BaseSchema):
    """Response schema for moderation queue items."""

    id: PydanticObjectId
    organization_id: PydanticObjectId
    content_type: ContentType
    content_id: PydanticObjectId
    embedding_vector: list[StrictFloat] | None
    status: ApprovalStatus
    reviewed_by_teacher_id: PydanticObjectId | None
    review_notes: StrictStr | None
    created_at: datetime
    reviewed_at: datetime | None


class ContentApprovalQueueUpdate(BaseSchema):
    """Request schema for moderation decision updates."""

    status: ApprovalStatus | None = None
    reviewed_by_teacher_id: PydanticObjectId | None = None
    review_notes: StrictStr | None = Field(default=None, max_length=2000)
    reviewed_at: datetime | None = None
    embedding_vector: list[StrictFloat] | None = Field(default=None, min_items=1, max_items=4096)
