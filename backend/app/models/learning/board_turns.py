from datetime import datetime
from typing import Any, Dict, Optional

from beanie import Document
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class SessionBoardTurn(Document):
    """Persisted VTSE / Timeline V3 board payload for session resume."""

    session_id: PydanticObjectId = Field(...)
    turn_index: int = Field(..., ge=0)
    content: str = Field(default="", max_length=120_000)
    instruction_timeline_v3: Optional[Dict[str, Any]] = Field(default=None)
    timeline_metadata: Optional[Dict[str, Any]] = Field(default=None)
    planner_source: Optional[str] = Field(default=None, max_length=64)
    visual: Optional[Dict[str, Any]] = Field(default=None)
    zone: Optional[int] = Field(default=None)
    cluster_index: Optional[int] = Field(default=None)
    concept_index: Optional[int] = Field(default=None)
    concept_id: Optional[str] = Field(default=None, max_length=500)
    response_type: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "session_board_turns"
        indexes = [
            IndexModel([("session_id", 1), ("turn_index", 1)]),
            IndexModel([("session_id", 1), ("created_at", 1)]),
        ]
