from datetime import datetime
from typing import Optional

from beanie import Document, Insert, Replace, before_event
from beanie.odm.fields import PydanticObjectId
from pydantic import Field


class TimestampedDocument(Document):
    """Document with created/updated timestamps (no tenant link)."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @before_event(Insert, Replace)
    def update_updated_at(self) -> None:
        """Set updated_at to current UTC time before save or replace."""
        self.updated_at = datetime.utcnow()


class BaseDocument(TimestampedDocument):
    """
    Document scoped to an organization (tenant), plus timestamps.
    Tenant-root documents (e.g. Organization) use TimestampedDocument instead.
    """

    organization_id: Optional[PydanticObjectId] = Field(default=None)
