from typing import Any, List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import ConfigDict, Field, field_validator
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.content.content_difficulty import normalize_content_difficulty_from_storage


NoteSourceType = Literal["admin", "teacher", "teacher_override", "ai"]
ConceptSourceType = Literal["legacy", "structured"]


class TopicNote(BaseDocument):
    """Reusable topic note authored or generated for cross-student reuse."""

    model_config = ConfigDict(populate_by_name=True)

    # None = platform-wide (admin) catalog; tenant notes use organization_id.
    organization_id: Optional[PydanticObjectId] = Field(default=None)
    topic_id: PydanticObjectId = Field(...)
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(..., min_length=1, max_length=64)
    note_type: Literal["summary", "detailed", "revision"] = Field(...)
    content_markdown: str = Field(..., min_length=1, max_length=25000)
    source_type: NoteSourceType = Field(default="teacher")
    teaching_style: Optional[str] = Field(default=None)
    interest_category: Optional[str] = Field(default=None)
    difficulty_level: str = Field(default="medium", min_length=1, max_length=20)
    # BSON key remains "embedding_vector" for existing documents (Beanie/Pydantic alias).
    embedding: Optional[List[float]] = Field(
        default=None,
        max_length=4096,
        alias="embedding_vector",
    )
    content_version: int = Field(default=1, ge=1)
    approved: bool = Field(default=False)
    usage_count: int = Field(default=0, ge=0)
    # None / missing in DB = general topic-wide note (not tied to one key concept).
    concept: Optional[str] = Field(default=None, max_length=500)
    concept_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="Optional FK to curriculum_concepts.id (structured authoring).",
    )
    concept_source: Optional[ConceptSourceType] = Field(default=None)

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_difficulty_level(cls, v: Any) -> str:
        return normalize_content_difficulty_from_storage(v)

    @field_validator("difficulty_level")
    @classmethod
    def validate_difficulty_level(cls, v: str) -> str:
        from app.models.content.content_difficulty import ALLOWED_CONTENT_DIFFICULTY

        s = (v or "").strip().lower()
        if s not in ALLOWED_CONTENT_DIFFICULTY:
            raise ValueError(
                'difficulty_level must be one of: "basic", "medium", "hard"'
            )
        return s

    @field_validator("concept", mode="before")
    @classmethod
    def normalize_concept(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().lower()
            return s if s else None
        raise TypeError("concept must be a string or null")

    @staticmethod
    def validate_concept_for_topic(topic: object, concept: Optional[str]) -> Optional[str]:
        """Trim, lowercase; must be None (general) or match one of topic.key_concepts."""
        from app.models.curriculum.topics import Topic as TopicModel

        if not isinstance(topic, TopicModel):
            raise TypeError("topic must be a Topic instance")
        if concept is None:
            return None
        normalized = (
            concept.strip().lower() if isinstance(concept, str) else None
        )
        if not normalized:
            return None
        allowed = {
            (kc.strip().lower() if isinstance(kc, str) else "") or ""
            for kc in (topic.key_concepts or [])
        }
        allowed.discard("")
        if normalized not in allowed:
            raise ValueError(
                "concept must be one of topic.key_concepts (after trim and lowercase)"
            )
        return normalized

    @staticmethod
    def validate_concept_for_teacher_topic(
        tt: object, concept: Optional[str]
    ) -> Optional[str]:
        """Like validate_concept_for_topic, but allowed list is TeacherTopic.key_concepts."""
        from app.models.teacher_topic import TeacherTopic as TeacherTopicModel

        if not isinstance(tt, TeacherTopicModel):
            raise TypeError("tt must be a TeacherTopic instance")
        if concept is None:
            return None
        normalized = (
            concept.strip().lower() if isinstance(concept, str) else None
        )
        if not normalized:
            return None
        allowed = {
            (kc.strip().lower() if isinstance(kc, str) else "") or ""
            for kc in (tt.key_concepts or [])
        }
        allowed.discard("")
        if not allowed:
            raise ValueError(
                "add key concepts to this teacher topic before tagging content"
            )
        if normalized not in allowed:
            raise ValueError(
                "concept must be one of this topic's key concepts (after trim and lowercase)"
            )
        return normalized

    class Settings:
        name = "topic_notes"
        indexes = [
            IndexModel([("organization_id", 1), ("topic_id", 1)]),
            IndexModel([("topic_id", 1), ("concept", 1)]),
            IndexModel(
                [("topic_id", 1), ("concept_id", 1)],
                name="idx_topic_concept_id",
                partialFilterExpression={"concept_id": {"$type": "objectId"}},
            ),
            IndexModel(
                [("concept_id", 1)],
                name="idx_concept_id",
                partialFilterExpression={"concept_id": {"$type": "objectId"}},
            ),
        ]
