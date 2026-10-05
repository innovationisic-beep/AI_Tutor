from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field, StrictBool, StrictFloat, StrictInt
from pymongo import IndexModel

from app.utils.timestamps import utc_now


class MasteryRecord(Document):
    """Aggregated mastery snapshot per student per topic."""

    organization_id: Indexed(PydanticObjectId) = Field(...)
    student_id: Indexed(PydanticObjectId) = Field(...)
    topic_id: Indexed(PydanticObjectId) = Field(...)
    mastery_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    confidence_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    teachback_average: StrictFloat = Field(..., ge=0.0, le=100.0)
    engagement_score: StrictFloat = Field(..., ge=0.0, le=100.0)
    revision_needed: StrictBool = Field(default=False)
    attempt_count: StrictInt = Field(default=0, ge=0)
    last_session_id: PydanticObjectId | None = Field(default=None)
    last_updated: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "mastery_records"
        indexes = [
            IndexModel(
                [("organization_id", 1), ("student_id", 1), ("topic_id", 1)],
                unique=True,
            ),
        ]
