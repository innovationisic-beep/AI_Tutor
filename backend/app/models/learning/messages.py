from datetime import datetime
from typing import Literal, Optional

from beanie import Document
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class SessionChatMessage(Document):
    """Persisted chat turn for a learning session (UI / audit; not used for tutor logic)."""

    session_id: PydanticObjectId = Field(...)
    role: Literal["user", "assistant"] = Field(...)
    content: str = Field(..., max_length=120_000)
    message_type: Optional[str] = Field(default=None, max_length=64)
    # Optional JSON snapshot for UI replay (e.g. action buttons on teacher flow).
    metadata_json: Optional[str] = Field(default=None, max_length=8_000)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "session_chat_messages"
        indexes = [
            IndexModel([("session_id", 1), ("created_at", 1)]),
        ]
