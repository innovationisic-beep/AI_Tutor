from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Assignment(BaseDocument):
    """Teacher-authored assignment record with reusable rubric context."""

    organization_id: PydanticObjectId = Field(...)
    topic_id: PydanticObjectId = Field(...)
    teacher_id: PydanticObjectId = Field(...)
    assignment_type: Literal["project", "essay", "problem_set"] = Field(...)
    description: str = Field(..., min_length=3, max_length=12000)
    rubric: str = Field(..., min_length=3, max_length=12000)
    embedding_vector: Optional[List[float]] = Field(default=None, max_length=4096)
    due_days: int = Field(..., ge=0)
    approved: bool = Field(default=False)

    class Settings:
        name = "assignments"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
        ]
