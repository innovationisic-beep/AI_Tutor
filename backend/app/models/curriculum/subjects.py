from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class Subject(BaseDocument):
    """Curriculum subject. ``organization_id`` null = platform catalog; else tenant-scoped."""

    organization_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="None = global admin catalog; set for organization-owned subjects.",
    )
    name: str = Field(..., min_length=2, max_length=120)
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=10, max_length=2000)
    academic_year: str = Field(..., min_length=4, max_length=20)
    curriculum_version: str = Field(..., min_length=1, max_length=20)
    status: Literal["draft", "active", "archived"] = Field(default="draft")
    is_active: bool = Field(default=True)

    class Settings:
        name = "subjects"
        indexes = [
            IndexModel([("organization_id", 1), ("grade", 1)]),
            IndexModel([("organization_id", 1), ("name", 1)]),
        ]
