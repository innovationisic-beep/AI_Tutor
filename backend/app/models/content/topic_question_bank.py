from typing import Any, List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import ConfigDict, Field, field_validator, model_validator
from pymongo import IndexModel

from app.models.base import BaseDocument
from app.models.content.content_difficulty import normalize_content_difficulty_from_storage

QuestionSourceType = Literal["admin", "teacher", "teacher_override", "ai"]
ConceptSourceType = Literal["legacy", "structured"]
QuizStage = Literal["concept_check", "cluster_quiz"]
QuestionType = Literal["mcq", "fill_in_blank", "descriptive"]


class TopicQuestionBank(BaseDocument):
    """Reusable question bank item scoped to topic and tenant."""

    model_config = ConfigDict(populate_by_name=True)

    # None = platform-wide (admin) catalog; tenant rows use organization_id.
    organization_id: Optional[PydanticObjectId] = Field(default=None)
    topic_id: PydanticObjectId = Field(...)
    difficulty_level: str = Field(default="medium", min_length=1, max_length=20)
    question_text: str = Field(..., min_length=3, max_length=5000)
    options: List[str] = Field(default_factory=list, max_length=10)
    correct_answer: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    explanation: str = Field(..., min_length=1, max_length=5000)
    source_type: QuestionSourceType = Field(default="teacher")
    # BSON key remains "embedding_vector" for existing documents (Beanie/Pydantic alias).
    embedding: Optional[List[float]] = Field(
        default=None,
        max_length=4096,
        alias="embedding_vector",
    )
    approved: bool = Field(default=False)
    usage_count: int = Field(default=0, ge=0)
    # None / missing in DB = general topic-wide question (not tied to one key concept).
    concept: Optional[str] = Field(default=None, max_length=500)
    concept_id: Optional[PydanticObjectId] = Field(
        default=None,
        description="Optional FK to curriculum_concepts.id (structured authoring).",
    )
    concept_source: Optional[ConceptSourceType] = Field(default=None)
    question_type: Optional[QuestionType] = Field(
        default=None,
        description="Explicit type; inferred from options/blank when null.",
    )
    # None = not eligible for structured concept-check / cluster-quiz bank selection.
    quiz_stage: Optional[QuizStage] = Field(
        default=None,
        description="Which structured quiz consumes this bank row.",
    )

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_difficulty_level(cls, v: Any) -> str:
        return normalize_content_difficulty_from_storage(v)

    @field_validator("question_type", mode="before")
    @classmethod
    def normalize_question_type(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("mcq", "fill_in_blank", "descriptive"):
            return s
        if s in ("fill-in-blank", "fill_in", "fill-in"):
            return "fill_in_blank"
        return None

    @field_validator("quiz_stage", mode="before")
    @classmethod
    def normalize_quiz_stage(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("concept_check", "cluster_quiz"):
            return s
        if not s:
            return None
        raise ValueError('quiz_stage must be "concept_check", "cluster_quiz", or null')

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

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise TypeError("options must be a list")
        out: list[str] = []
        for item in v:
            s = str(item).strip()
            if not s:
                raise ValueError("options cannot contain empty values")
            out.append(s)
        return out

    @field_validator("correct_answer", mode="before")
    @classmethod
    def normalize_correct_answer(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @model_validator(mode="after")
    def validate_question_shape(self) -> "TopicQuestionBank":
        from app.services.handlers.concept_check_question_types import (
            has_blank_marker,
            infer_bank_question_type,
        )

        qtype = infer_bank_question_type(self)
        if qtype == "fill_in_blank":
            if not has_blank_marker(self.question_text):
                raise ValueError("fill_in_blank requires a blank marker (____) in question_text")
            if not (self.correct_answer or "").strip():
                raise ValueError("fill_in_blank requires correct_answer")
            return self
        if qtype == "descriptive":
            return self
        # MCQ: require >=2 options and answer among options.
        if len(self.options) < 2:
            raise ValueError("MCQ requires at least 2 options")
        if self.correct_answer is None:
            raise ValueError("correct_answer is required when options are provided")
        if self.correct_answer not in self.options:
            raise ValueError("correct_answer must be one of the options")
        return self

    @staticmethod
    def validate_concept_for_topic(topic: object, concept: Optional[str]) -> Optional[str]:
        from app.models.content.topic_notes import TopicNote

        return TopicNote.validate_concept_for_topic(topic, concept)

    @staticmethod
    def validate_concept_for_teacher_topic(
        tt: object, concept: Optional[str]
    ) -> Optional[str]:
        from app.models.content.topic_notes import TopicNote

        return TopicNote.validate_concept_for_teacher_topic(tt, concept)

    class Settings:
        name = "topic_question_bank"
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
