"""Platform admin APIs: global (organization_id null) catalog notes and questions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.teacher_topic_service import validate_concept_clusters

from app.core.dependencies import get_current_admin
from app.models.content.content_difficulty import parse_content_difficulty_strict
from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.subjects import Subject
from app.models.curriculum.topics import Topic
from app.repositories.topic_note_repository import (
    TopicNoteRepository,
    get_topic_note_repository,
    normalize_concept_filter,
    validate_concept_for_topic,
)
from app.repositories.topic_question_repository import (
    TopicQuestionRepository,
    get_topic_question_repository,
)
from app.services.curriculum.content_concept_link_service import (
    ContentConceptLinkService,
)
from app.repositories.topic_repository import TopicRepository, get_topic_repository
from app.api.schemas.learning_graph import (
    CreatePrerequisiteRequest,
    CreateProgressionRequest,
    PrerequisiteEdgeOut,
    ProgressionEdgeOut,
)
from app.services import learning_graph_service as learning_graph_svc

router = APIRouter(prefix="/admin", tags=["Admin content"])


def _slugify_topic_name(name: str) -> str:
    x = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (x[:160] if x else "topic")


async def _unique_global_topic_slug(
    base_slug: str,
    *,
    exclude_topic_id: Optional[PydanticObjectId] = None,
) -> str:
    """Pick a unique global ``topic_slug``; ``exclude_topic_id`` skips collision with that topic (for updates)."""
    slug = base_slug[:160]
    if not slug:
        slug = "topic"
    candidate = slug
    n = 0
    while True:
        dup = await Topic.find_one({"organization_id": None, "topic_slug": candidate})
        if dup is None:
            return candidate
        if exclude_topic_id is not None and dup.id == exclude_topic_id:
            return candidate
        n += 1
        suffix = f"-{n}"
        candidate = (slug[: 160 - len(suffix)] + suffix) if len(suffix) < 160 else slug


async def _assert_unique_global_subject_name_grade(
    name: str,
    grade: str,
    *,
    exclude_subject_id: Optional[PydanticObjectId] = None,
) -> None:
    g = grade.strip()
    key = name.strip().lower()
    rows = await Subject.find(
        {"organization_id": None, "grade": g},
    ).to_list()
    for s in rows:
        if exclude_subject_id is not None and s.id == exclude_subject_id:
            continue
        if s.name.strip().lower() == key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A global subject with this name and grade already exists",
            )


async def _require_global_subject(subject_id: PydanticObjectId) -> Subject:
    s = await Subject.get(subject_id)
    if s is None or s.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Global catalog subject not found",
        )
    return s


async def _require_global_topic(topic_id: PydanticObjectId) -> Topic:
    t = await Topic.get(topic_id)
    if t is None or t.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Global catalog topic not found",
        )
    return t


class IdResponse(BaseModel):
    id: str


class AdminCreateSubjectRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(default="General", min_length=1, max_length=64)
    description: str = Field(
        default="Curriculum subject — add a fuller description as needed.",
        min_length=10,
        max_length=2000,
    )
    academic_year: str = Field(default="2024", min_length=4, max_length=20)
    curriculum_version: str = Field(default="v1", min_length=1, max_length=20)
    status: Literal["draft", "active", "archived"] = "active"
    is_active: bool = True


class AdminUpdateSubjectRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    grade: str = Field(..., min_length=1, max_length=32)
    board: str = Field(default="General", min_length=1, max_length=64)
    description: str = Field(
        default="Curriculum subject — add a fuller description as needed.",
        min_length=10,
        max_length=2000,
    )
    academic_year: str = Field(default="2024", min_length=4, max_length=20)
    curriculum_version: str = Field(default="v1", min_length=1, max_length=20)
    status: Literal["draft", "active", "archived"] = "active"
    is_active: bool = True


class AdminSubjectOut(BaseModel):
    id: str
    name: str
    grade: str
    board: str
    description: str
    academic_year: str
    curriculum_version: str
    status: str
    is_active: bool


class AdminTopicOut(BaseModel):
    id: str
    subject_id: str
    topic_name: str
    topic_slug: str
    topic_description: str
    key_concepts: List[str]
    concept_clusters: Optional[List[List[str]]] = None
    difficulty_level: str
    default_depth: str
    topic_order: int
    estimated_time: int
    status: str
    is_active: bool


class AdminCreateTopicRequest(BaseModel):
    subject_id: str = Field(..., min_length=24, max_length=24)
    topic_name: str = Field(..., min_length=2, max_length=140)
    topic_slug: Optional[str] = Field(default=None, max_length=160)
    topic_description: str = Field(..., min_length=10, max_length=3000)
    learning_objectives: List[str] = Field(default_factory=list, max_length=100)
    learning_outcomes: List[str] = Field(default_factory=list, max_length=100)
    key_concepts: List[str] = Field(default_factory=list, max_length=100)
    concept_clusters: Optional[List[List[str]]] = Field(
        default=None,
        description=(
            "Optional grouping of key_concepts into clusters. "
            "Every concept must exist in key_concepts; no duplicates across clusters."
        ),
    )
    common_mistakes: List[str] = Field(default_factory=list, max_length=100)
    difficulty_level: str = Field(default="medium", min_length=1, max_length=20)
    topic_order: int = Field(default=0, ge=0)
    estimated_time: int = Field(default=30, ge=1, le=1440)
    default_depth: str = Field(default="standard", min_length=1, max_length=20)
    academic_year: str = Field(default="2024", min_length=4, max_length=20)
    curriculum_version: str = Field(default="v1", min_length=1, max_length=20)
    status: Literal["draft", "active", "archived"] = "active"
    is_active: bool = True

    @model_validator(mode="after")
    def _check_clusters(self) -> "AdminCreateTopicRequest":
        try:
            validate_concept_clusters(self.key_concepts, self.concept_clusters)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class AdminUpdateTopicRequest(BaseModel):
    topic_name: str = Field(..., min_length=2, max_length=140)
    topic_slug: Optional[str] = Field(default=None, max_length=160)
    topic_description: str = Field(..., min_length=10, max_length=3000)
    key_concepts: List[str] = Field(default_factory=list, max_length=100)
    concept_clusters: Optional[List[List[str]]] = Field(
        default=None,
        description=(
            "Optional grouping of key_concepts into clusters. "
            "Every concept must exist in key_concepts; no duplicates across clusters. "
            "Pass null to clear existing clusters (auto-derive will be used instead)."
        ),
    )
    difficulty_level: str = Field(default="medium", min_length=1, max_length=20)
    default_depth: str = Field(default="standard", min_length=1, max_length=20)
    topic_order: int = Field(default=0, ge=0)
    estimated_time: int = Field(default=30, ge=1, le=1440)
    academic_year: str = Field(default="2024", min_length=4, max_length=20)
    curriculum_version: str = Field(default="v1", min_length=1, max_length=20)
    status: Literal["draft", "active", "archived"] = "active"
    is_active: bool = True

    @model_validator(mode="after")
    def _check_clusters(self) -> "AdminUpdateTopicRequest":
        try:
            validate_concept_clusters(self.key_concepts, self.concept_clusters)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class AdminTopicNoteOut(BaseModel):
    id: str
    topic_id: str
    concept: Optional[str] = None
    concept_id: Optional[str] = None
    concept_source: Optional[str] = None
    content: str
    note_type: str
    difficulty_level: str
    teaching_style: Optional[str] = None
    interest_category: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AdminTopicQuestionOut(BaseModel):
    id: str
    topic_id: str
    concept: Optional[str] = None
    concept_id: Optional[str] = None
    concept_source: Optional[str] = None
    content: str
    options: List[str]
    correct_answer: Optional[str] = None
    explanation: str
    difficulty_level: str
    question_type: Optional[str] = None
    quiz_stage: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def _note_to_admin_out(note: TopicNote) -> AdminTopicNoteOut:
    return AdminTopicNoteOut(
        id=str(note.id),
        topic_id=str(note.topic_id),
        concept=note.concept,
        concept_id=str(note.concept_id) if note.concept_id else None,
        concept_source=note.concept_source,
        content=note.content_markdown,
        note_type=str(note.note_type),
        difficulty_level=str(note.difficulty_level),
        teaching_style=note.teaching_style,
        interest_category=note.interest_category,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _question_to_admin_out(q: TopicQuestionBank) -> AdminTopicQuestionOut:
    return AdminTopicQuestionOut(
        id=str(q.id),
        topic_id=str(q.topic_id),
        concept=q.concept,
        concept_id=str(q.concept_id) if q.concept_id else None,
        concept_source=q.concept_source,
        content=q.question_text,
        options=list(q.options or []),
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        difficulty_level=str(q.difficulty_level),
        question_type=getattr(q, "question_type", None),
        quiz_stage=getattr(q, "quiz_stage", None),
        created_at=q.created_at,
        updated_at=q.updated_at,
    )


class AdminUpdateTopicNoteRequest(BaseModel):
    content_markdown: str = Field(..., min_length=1, max_length=25000)
    note_type: Literal["summary", "detailed", "revision"]
    difficulty_level: str = Field(default="medium")
    teaching_style: Optional[str] = None
    interest_category: Optional[str] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_admin_note_difficulty_u(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)


class AdminUpdateQuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=3, max_length=5000)
    options: List[str] = Field(default_factory=list, max_length=10)
    correct_answer: Optional[str] = Field(default=None, max_length=2000)
    explanation: str = Field(default="", max_length=5000)
    difficulty_level: str = Field(default="medium")
    question_type: Optional[Literal["mcq", "fill_in_blank", "descriptive"]] = None
    quiz_stage: Optional[Literal["concept_check", "cluster_quiz"]] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_admin_q_diff(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)

    @field_validator("question_type", mode="before")
    @classmethod
    def normalize_question_type_u(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("mcq", "fill_in_blank", "descriptive"):
            return s
        if s in ("fill-in-blank", "fill_in", "fill-in", "fill_blank"):
            return "fill_in_blank"
        return None

    @field_validator("quiz_stage", mode="before")
    @classmethod
    def normalize_quiz_stage_u(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("concept_check", "cluster_quiz"):
            return s
        if not s:
            return None
        raise ValueError('quiz_stage must be "concept_check", "cluster_quiz", or null')

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options_a(cls, v: object) -> list[str]:
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
    def normalize_ca_a(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @model_validator(mode="after")
    def validate_shape(self) -> "AdminUpdateQuestionRequest":
        if len(self.options) == 0:
            return self
        if len(self.options) < 2:
            raise ValueError("MCQ requires at least 2 options")
        if self.correct_answer is None:
            raise ValueError("correct_answer is required when options are provided")
        if self.correct_answer not in self.options:
            raise ValueError("correct_answer must be one of the options")
        if not (self.explanation or "").strip():
            raise ValueError("explanation is required for MCQ questions")
        return self


class AdminCreateTopicNoteRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    concept: Optional[str] = None
    concept_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    structured: bool = Field(
        default=False,
        description="When true, concept_id is required for v2 structured authoring.",
    )
    content_markdown: str = Field(..., min_length=1, max_length=25000)
    note_type: Literal["summary", "detailed", "revision"]
    difficulty_level: str = Field(default="medium")
    teaching_style: Optional[str] = None
    interest_category: Optional[str] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_admin_note_difficulty(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)


class AdminCreateQuestionRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    concept: Optional[str] = None
    concept_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    structured: bool = Field(
        default=False,
        description="When true, concept_id is required for v2 structured authoring.",
    )
    question_text: str = Field(..., min_length=3, max_length=5000)
    options: List[str] = Field(default_factory=list, max_length=10)
    correct_answer: Optional[str] = Field(default=None, max_length=2000)
    explanation: str = Field(default="", max_length=5000)
    difficulty_level: str = Field(default="medium")
    question_type: Optional[Literal["mcq", "fill_in_blank", "descriptive"]] = None
    quiz_stage: Optional[Literal["concept_check", "cluster_quiz"]] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def coerce_admin_question_difficulty(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)

    @field_validator("question_type", mode="before")
    @classmethod
    def normalize_question_type_c(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("mcq", "fill_in_blank", "descriptive"):
            return s
        if s in ("fill-in-blank", "fill_in", "fill-in", "fill_blank"):
            return "fill_in_blank"
        return None

    @field_validator("quiz_stage", mode="before")
    @classmethod
    def normalize_quiz_stage_c(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("concept_check", "cluster_quiz"):
            return s
        if not s:
            return None
        raise ValueError('quiz_stage must be "concept_check", "cluster_quiz", or null')

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options_c(cls, v: object) -> list[str]:
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
    def normalize_ca_c(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @model_validator(mode="after")
    def validate_create_shape(self) -> "AdminCreateQuestionRequest":
        if (self.concept_id or self.structured) and not self.quiz_stage:
            raise ValueError(
                "quiz_stage is required when concept_id is set or structured=true"
            )
        if len(self.options) == 0:
            return self
        if len(self.options) < 2:
            raise ValueError("MCQ requires at least 2 options")
        if self.correct_answer is None:
            raise ValueError("correct_answer is required when options are provided")
        if self.correct_answer not in self.options:
            raise ValueError("correct_answer must be one of the options")
        if not (self.explanation or "").strip():
            raise ValueError("explanation is required for MCQ questions")
        return self


async def _global_catalog_topic(
    topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic:
    topic = await topic_repository.get_by_id(topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )
    if topic.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin catalog notes and questions must use a global topic (organization_id null)",
        )
    return topic


@router.post(
    "/subject",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_subject(body: AdminCreateSubjectRequest) -> IdResponse:
    await _assert_unique_global_subject_name_grade(body.name, body.grade)
    desc = body.description.strip()
    if len(desc) < 10:
        desc = (desc + " " * (10 - len(desc)))[:2000]
    subject = Subject(
        organization_id=None,
        name=body.name.strip(),
        grade=body.grade.strip(),
        board=(body.board or "General").strip() or "General",
        description=desc,
        academic_year=body.academic_year.strip(),
        curriculum_version=body.curriculum_version.strip(),
        status=body.status,
        is_active=body.is_active,
    )
    await subject.insert()
    return IdResponse(id=str(subject.id))


@router.post(
    "/topic",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_topic(
    body: AdminCreateTopicRequest,
) -> IdResponse:
    try:
        sid = PydanticObjectId(body.subject_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject_id")
    await _require_global_subject(sid)
    raw_slug = (body.topic_slug or "").strip().lower()
    base = raw_slug or _slugify_topic_name(body.topic_name)
    slug = await _unique_global_topic_slug(base)
    topic = Topic(
        organization_id=None,
        subject_id=sid,
        topic_name=body.topic_name.strip(),
        topic_slug=slug,
        topic_description=body.topic_description.strip(),
        learning_objectives=list(body.learning_objectives or []),
        learning_outcomes=list(body.learning_outcomes or []),
        key_concepts=list(body.key_concepts or []),
        concept_clusters=body.concept_clusters,
        common_mistakes=list(body.common_mistakes or []),
        difficulty_level=body.difficulty_level.strip(),
        topic_order=body.topic_order,
        estimated_time=body.estimated_time,
        default_depth=body.default_depth.strip(),
        academic_year=body.academic_year.strip(),
        curriculum_version=body.curriculum_version.strip(),
        status=body.status,
        is_active=body.is_active,
    )
    await topic.insert()
    return IdResponse(id=str(topic.id))


@router.post(
    "/topic-note",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_topic_note(
    body: AdminCreateTopicNoteRequest,
    topic_repository: TopicRepository = Depends(get_topic_repository),
    note_repository: TopicNoteRepository = Depends(get_topic_note_repository),
) -> IdResponse:
    try:
        tid = PydanticObjectId(body.topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    topic = await _global_catalog_topic(tid, topic_repository)
    grade = (topic.default_depth or "standard")[:32]
    board = "general"
    schema_version = getattr(topic, "curriculum_schema_version", "v1") or "v1"
    link = await ContentConceptLinkService().resolve_for_authoring(
        curriculum_schema_version=schema_version,
        topic_id=tid,
        topic_source="catalog",
        organization_id=None,
        concept_id=body.concept_id,
        concept=body.concept,
        is_structured_flow=body.structured,
        topic=topic,
    )
    note = await note_repository.create(
        {
            "organization_id": None,
            "topic_id": tid,
            "grade": grade,
            "board": board,
            "note_type": body.note_type,
            "content_markdown": body.content_markdown,
            "source_type": "admin",
            "teaching_style": (body.teaching_style or "").strip() or None,
            "interest_category": (body.interest_category or "").strip() or None,
            "difficulty_level": body.difficulty_level,
            "approved": True,
            "usage_count": 0,
            "concept": link.concept,
            "concept_id": link.concept_id,
            "concept_source": link.concept_source,
        }
    )
    return IdResponse(id=str(note.id))


@router.post(
    "/question",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_question(
    body: AdminCreateQuestionRequest,
    topic_repository: TopicRepository = Depends(get_topic_repository),
    question_repository: TopicQuestionRepository = Depends(get_topic_question_repository),
) -> IdResponse:
    try:
        tid = PydanticObjectId(body.topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    topic = await _global_catalog_topic(tid, topic_repository)
    schema_version = getattr(topic, "curriculum_schema_version", "v1") or "v1"
    link = await ContentConceptLinkService().resolve_for_authoring(
        curriculum_schema_version=schema_version,
        topic_id=tid,
        topic_source="catalog",
        organization_id=None,
        concept_id=body.concept_id,
        concept=body.concept,
        is_structured_flow=body.structured,
        topic=topic,
    )
    from app.services.handlers.concept_check_question_types import has_blank_marker
    from app.services.curriculum.question_bank_stage_service import assert_quiz_stage_caps
    from app.models.curriculum.curriculum_concept import CurriculumConcept

    inferred_type = body.question_type
    if not inferred_type:
        if len(body.options or []) >= 2:
            inferred_type = "mcq"
        elif has_blank_marker(body.question_text) and (body.correct_answer or "").strip():
            inferred_type = "fill_in_blank"
        else:
            inferred_type = "descriptive"
    if body.quiz_stage and link.concept_id is not None:
        concept = await CurriculumConcept.get(link.concept_id)
        if concept is not None and concept.deleted_at is None:
            await assert_quiz_stage_caps(
                concept=concept,
                quiz_stage=body.quiz_stage,
                question_type=inferred_type,
            )
    q = await question_repository.create(
        {
            "organization_id": None,
            "topic_id": tid,
            "difficulty_level": body.difficulty_level,
            "question_text": body.question_text,
            "options": body.options,
            "correct_answer": body.correct_answer,
            "explanation": body.explanation,
            "source_type": "admin",
            "approved": True,
            "usage_count": 0,
            "concept": link.concept,
            "concept_id": link.concept_id,
            "concept_source": link.concept_source,
            "question_type": inferred_type,
            "quiz_stage": body.quiz_stage,
        }
    )
    return IdResponse(id=str(q.id))


# --- Catalog listing & full CRUD -------------------------------------------------


@router.get(
    "/catalog/subjects",
    response_model=List[AdminSubjectOut],
    dependencies=[Depends(get_current_admin)],
)
async def list_catalog_subjects() -> List[AdminSubjectOut]:
    rows = await Subject.find({"organization_id": None}).sort(
        [("grade", 1), ("name", 1)]
    ).to_list()
    return [
        AdminSubjectOut(
            id=str(s.id),
            name=s.name,
            grade=s.grade,
            board=s.board,
            description=s.description,
            academic_year=s.academic_year,
            curriculum_version=s.curriculum_version,
            status=str(s.status),
            is_active=bool(s.is_active),
        )
        for s in rows
    ]


@router.get(
    "/catalog/topics",
    response_model=List[AdminTopicOut],
    dependencies=[Depends(get_current_admin)],
)
async def list_catalog_topics(
    subject_id: str = Query(..., min_length=24, max_length=24),
) -> List[AdminTopicOut]:
    try:
        sid = PydanticObjectId(subject_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject_id")
    await _require_global_subject(sid)
    rows = await Topic.find({"organization_id": None, "subject_id": sid}).sort(
        [("topic_order", 1), ("topic_name", 1)]
    ).to_list()
    return [
        AdminTopicOut(
            id=str(t.id),
            subject_id=str(t.subject_id),
            topic_name=t.topic_name,
            topic_slug=t.topic_slug,
            topic_description=t.topic_description,
            key_concepts=list(t.key_concepts or []),
            concept_clusters=t.concept_clusters,
            difficulty_level=t.difficulty_level,
            default_depth=t.default_depth,
            topic_order=int(t.topic_order),
            estimated_time=int(t.estimated_time),
            status=str(t.status),
            is_active=bool(t.is_active),
        )
        for t in rows
    ]


@router.put(
    "/subject/{subject_id}",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_update_subject(
    subject_id: str,
    body: AdminUpdateSubjectRequest,
) -> IdResponse:
    try:
        sid = PydanticObjectId(subject_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject_id")
    subj = await _require_global_subject(sid)
    await _assert_unique_global_subject_name_grade(
        body.name,
        body.grade,
        exclude_subject_id=subj.id,
    )
    desc = body.description.strip()
    if len(desc) < 10:
        desc = (desc + " " * (10 - len(desc)))[:2000]
    subj.name = body.name.strip()
    subj.grade = body.grade.strip()
    subj.board = (body.board or "General").strip() or "General"
    subj.description = desc
    subj.academic_year = body.academic_year.strip()
    subj.curriculum_version = body.curriculum_version.strip()
    subj.status = body.status
    subj.is_active = body.is_active
    await subj.save()
    return IdResponse(id=str(subj.id))


@router.delete(
    "/subject/{subject_id}",
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_subject(subject_id: str) -> dict:
    try:
        sid = PydanticObjectId(subject_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject_id")
    subj = await _require_global_subject(sid)
    topics = await Topic.find(
        {"organization_id": None, "subject_id": sid}
    ).to_list()
    for t in topics:
        await TopicNote.find(
            {"topic_id": t.id, "organization_id": None}
        ).delete()
        await TopicQuestionBank.find(
            {"topic_id": t.id, "organization_id": None}
        ).delete()
        await t.delete()
    await subj.delete()
    return {"ok": True}


@router.put(
    "/topic/{topic_id}",
    response_model=IdResponse,
    dependencies=[Depends(get_current_admin)],
)
async def admin_update_topic(
    topic_id: str,
    body: AdminUpdateTopicRequest,
) -> IdResponse:
    try:
        tid = PydanticObjectId(topic_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    topic = await _require_global_topic(tid)
    name_changed = body.topic_name.strip() != (topic.topic_name or "").strip()
    if name_changed:
        base = _slugify_topic_name(body.topic_name.strip())
        new_slug = await _unique_global_topic_slug(
            base, exclude_topic_id=topic.id
        )
    else:
        raw_slug = (body.topic_slug or "").strip().lower()
        new_slug = raw_slug or topic.topic_slug
    if new_slug != topic.topic_slug:
        dup = await Topic.find_one(
            {"organization_id": None, "topic_slug": new_slug}
        )
        if dup is not None and dup.id != topic.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A global topic with this topic_slug already exists",
            )
    topic.topic_name = body.topic_name.strip()
    topic.topic_slug = new_slug
    topic.topic_description = body.topic_description.strip()
    topic.key_concepts = list(body.key_concepts or [])
    topic.concept_clusters = body.concept_clusters
    topic.difficulty_level = body.difficulty_level.strip()
    topic.default_depth = body.default_depth.strip()
    topic.topic_order = body.topic_order
    topic.estimated_time = body.estimated_time
    topic.academic_year = body.academic_year.strip()
    topic.curriculum_version = body.curriculum_version.strip()
    topic.status = body.status
    topic.is_active = body.is_active
    await topic.save()
    return IdResponse(id=str(topic.id))


@router.delete(
    "/topic/{topic_id}",
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_topic(topic_id: str) -> dict:
    try:
        tid = PydanticObjectId(topic_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    topic = await _require_global_topic(tid)
    await TopicNote.find({"topic_id": tid, "organization_id": None}).delete()
    await TopicQuestionBank.find({"topic_id": tid, "organization_id": None}).delete()
    await topic.delete()
    return {"ok": True}


@router.get(
    "/catalog/topic-notes",
    response_model=List[AdminTopicNoteOut],
    dependencies=[Depends(get_current_admin)],
)
async def list_catalog_topic_notes(
    topic_id: str = Query(..., min_length=24, max_length=24),
    concept: Optional[str] = Query(
        default=None,
        description="Omit for all notes; empty string for topic-wide (null concept)",
    ),
) -> List[AdminTopicNoteOut]:
    try:
        tid = PydanticObjectId(topic_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    await _require_global_topic(tid)
    if concept is None:
        rows = await TopicNote.find(
            {"organization_id": None, "topic_id": tid}
        ).sort([("created_at", -1)]).to_list()
    else:
        c = concept.strip()
        if not c:
            rows = await TopicNote.find(
                {
                    "organization_id": None,
                    "topic_id": tid,
                    "concept": None,
                }
            ).sort([("created_at", -1)]).to_list()
        else:
            nc = normalize_concept_filter(c)
            if nc is None:
                rows = []
            else:
                rows = await TopicNote.find(
                    {
                        "organization_id": None,
                        "topic_id": tid,
                        "concept": nc,
                    }
                ).sort([("created_at", -1)]).to_list()
    return [_note_to_admin_out(n) for n in rows]


@router.put(
    "/topic-note/{note_id}",
    response_model=AdminTopicNoteOut,
    dependencies=[Depends(get_current_admin)],
)
async def admin_update_topic_note(
    note_id: str,
    body: AdminUpdateTopicNoteRequest,
) -> AdminTopicNoteOut:
    try:
        nid = PydanticObjectId(note_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note_id")
    note = await TopicNote.get(nid)
    if note is None or note.organization_id is not None:
        raise HTTPException(status_code=404, detail="Catalog note not found")
    note.content_markdown = body.content_markdown
    note.note_type = body.note_type
    note.difficulty_level = body.difficulty_level
    note.teaching_style = (body.teaching_style or "").strip() or None
    note.interest_category = (body.interest_category or "").strip() or None
    await note.save()
    return _note_to_admin_out(note)


@router.delete(
    "/topic-note/{note_id}",
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_topic_note(note_id: str) -> dict:
    try:
        nid = PydanticObjectId(note_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note_id")
    note = await TopicNote.get(nid)
    if note is None or note.organization_id is not None:
        raise HTTPException(status_code=404, detail="Catalog note not found")
    await note.delete()
    return {"ok": True}


@router.put(
    "/question/{question_id}",
    response_model=AdminTopicQuestionOut,
    dependencies=[Depends(get_current_admin)],
)
async def admin_update_question(
    question_id: str,
    body: AdminUpdateQuestionRequest,
) -> AdminTopicQuestionOut:
    try:
        qid = PydanticObjectId(question_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    row = await TopicQuestionBank.get(qid)
    if row is None or row.organization_id is not None:
        raise HTTPException(status_code=404, detail="Catalog question not found")
    from app.services.handlers.concept_check_question_types import has_blank_marker
    from app.services.curriculum.question_bank_stage_service import assert_quiz_stage_caps
    from app.models.curriculum.curriculum_concept import CurriculumConcept

    inferred_type = body.question_type
    if not inferred_type:
        if len(body.options or []) >= 2:
            inferred_type = "mcq"
        elif has_blank_marker(body.question_text) and (body.correct_answer or "").strip():
            inferred_type = "fill_in_blank"
        else:
            inferred_type = "descriptive"
    stage = body.quiz_stage if body.quiz_stage is not None else getattr(row, "quiz_stage", None)
    if row.concept_id is not None and not stage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="quiz_stage is required for concept-linked questions",
        )
    if stage and row.concept_id is not None:
        concept = await CurriculumConcept.get(row.concept_id)
        if concept is not None and concept.deleted_at is None:
            await assert_quiz_stage_caps(
                concept=concept,
                quiz_stage=stage,
                question_type=inferred_type,
                exclude_question_id=row.id,
            )
    row.question_text = body.question_text
    row.options = list(body.options or [])
    row.correct_answer = body.correct_answer
    row.explanation = body.explanation
    row.difficulty_level = body.difficulty_level
    row.question_type = inferred_type  # type: ignore[assignment]
    if body.quiz_stage is not None:
        row.quiz_stage = body.quiz_stage  # type: ignore[assignment]
    await row.save()
    return _question_to_admin_out(row)


@router.delete(
    "/question/{question_id}",
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_question(question_id: str) -> dict:
    try:
        qid = PydanticObjectId(question_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    row = await TopicQuestionBank.get(qid)
    if row is None or row.organization_id is not None:
        raise HTTPException(status_code=404, detail="Catalog question not found")
    await row.delete()
    return {"ok": True}


# --- Learning graph (global catalog: organization_id null on edges) ---


@router.post(
    "/prerequisite",
    response_model=PrerequisiteEdgeOut,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_prerequisite(
    body: CreatePrerequisiteRequest,
) -> PrerequisiteEdgeOut:
    tid = learning_graph_svc.parse_topic_oid(body.topic_id, "topic_id")
    pid = learning_graph_svc.parse_topic_oid(
        body.prerequisite_topic_id, "prerequisite_topic_id"
    )
    row = await learning_graph_svc.create_prerequisite_edge(
        topic_id=tid,
        prerequisite_topic_id=pid,
        organization_id=None,
        mode="admin",
        user_org_id=None,
    )
    return PrerequisiteEdgeOut(
        id=str(row.id),
        topic_id=str(row.topic_id),
        prerequisite_topic_id=str(row.prerequisite_topic_id),
    )


@router.get(
    "/prerequisites",
    response_model=List[PrerequisiteEdgeOut],
    dependencies=[Depends(get_current_admin)],
)
async def admin_list_prerequisites(
    topic_id: str = Query(..., min_length=24, max_length=24),
) -> List[PrerequisiteEdgeOut]:
    tid = learning_graph_svc.parse_topic_oid(topic_id, "topic_id")
    rows = await learning_graph_svc.list_prerequisites_admin(tid)
    return [PrerequisiteEdgeOut(**r) for r in rows]


@router.delete(
    "/prerequisite/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_prerequisite(edge_id: str) -> None:
    eid = learning_graph_svc.parse_topic_oid(edge_id, "edge_id")
    await learning_graph_svc.delete_prerequisite_admin(eid)


@router.post(
    "/progression",
    response_model=ProgressionEdgeOut,
    dependencies=[Depends(get_current_admin)],
)
async def admin_create_progression(
    body: CreateProgressionRequest,
) -> ProgressionEdgeOut:
    tid = learning_graph_svc.parse_topic_oid(body.topic_id, "topic_id")
    nid = learning_graph_svc.parse_topic_oid(
        body.recommended_next_topic_id, "recommended_next_topic_id"
    )
    row = await learning_graph_svc.create_progression_edge(
        topic_id=tid,
        recommended_next_topic_id=nid,
        minimum_mastery=float(body.minimum_mastery_to_recommend),
        organization_id=None,
        mode="admin",
        user_org_id=None,
    )
    return ProgressionEdgeOut(
        id=str(row.id),
        topic_id=str(row.topic_id),
        recommended_next_topic_id=str(row.recommended_next_topic_id),
        minimum_mastery_to_recommend=int(
            round(float(row.minimum_mastery_to_recommend))
        ),
    )


@router.get(
    "/progression",
    response_model=List[ProgressionEdgeOut],
    dependencies=[Depends(get_current_admin)],
)
async def admin_list_progression(
    topic_id: str = Query(..., min_length=24, max_length=24),
) -> List[ProgressionEdgeOut]:
    tid = learning_graph_svc.parse_topic_oid(topic_id, "topic_id")
    rows = await learning_graph_svc.list_progression_admin(tid)
    return [ProgressionEdgeOut(**r) for r in rows]


@router.delete(
    "/progression/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_admin)],
)
async def admin_delete_progression(edge_id: str) -> None:
    eid = learning_graph_svc.parse_topic_oid(edge_id, "edge_id")
    await learning_graph_svc.delete_progression_admin(eid)
