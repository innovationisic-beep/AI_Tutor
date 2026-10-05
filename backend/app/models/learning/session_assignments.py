from typing import Any, List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class SessionAssignment(BaseDocument):
    """AI-generated practice assignment created after a learning session (distinct from teacher Assignment)."""

    organization_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    session_id: Optional[PydanticObjectId] = Field(default=None)
    questions: List[Any] = Field(default_factory=list)
    difficulty_level: Literal["easy", "medium", "hard"] = Field(...)
    status: Literal["pending", "completed", "cancelled"] = Field(default="pending")
    score: Optional[float] = Field(default=None)
    focus_concepts: List[str] = Field(default_factory=list)

    class Settings:
        name = "session_assignments"
        indexes = [
            IndexModel([("organization_id", 1), ("student_id", 1), ("topic_id", 1)]),
        ]
