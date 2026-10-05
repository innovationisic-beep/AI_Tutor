"""Teacher (and admin) content APIs: org-scoped notes, questions, and overrides."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.dependencies import get_current_teacher_or_admin
from app.models.content.content_difficulty import (
    difficulty_for_json,
    parse_content_difficulty_strict,
)
from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.topics import Topic
from app.models.identification.users import User
from app.models.organization import Organization
from app.models.teacher_topic import TeacherTopic
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

router = APIRouter(prefix="/teacher", tags=["Teacher"])

_TEACHING_STYLES = frozenset({"conceptual", "practical", "exam-oriented", "visual"})
_INTEREST_CATEGORIES = frozenset({"general", "real-life", "advanced", "fun"})


class IdResponse(BaseModel):
    id: str


class DeleteSuccessResponse(BaseModel):
    success: bool = True


class CreateTopicNoteRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    concept: Optional[str] = None
    concept_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    structured: bool = Field(default=False)
    content_markdown: str = Field(..., min_length=1, max_length=25000)
    note_type: Literal["summary", "detailed", "revision"] = "detailed"
    difficulty_level: str = Field(default="medium")
    teaching_style: Optional[str] = None
    interest_category: Optional[str] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def validate_note_difficulty(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)

    @field_validator("teaching_style", mode="before")
    @classmethod
    def validate_teaching_style(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = str(v).strip().lower()
        if s not in _TEACHING_STYLES:
            raise ValueError(
                "teaching_style must be one of: conceptual, practical, "
                "exam-oriented, visual"
            )
        return s

    @field_validator("interest_category", mode="before")
    @classmethod
    def validate_interest_category(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = str(v).strip().lower()
        if s not in _INTEREST_CATEGORIES:
            raise ValueError(
                "interest_category must be one of: general, real-life, "
                "advanced, fun"
            )
        return s


class OverrideTopicNoteRequest(BaseModel):
    content_markdown: str = Field(..., min_length=1, max_length=25000)


class UpdateTopicNoteRequest(BaseModel):
    content_markdown: str = Field(..., min_length=1, max_length=25000)
    note_type: Literal["summary", "detailed", "revision"] = "detailed"
    difficulty_level: str = Field(default="medium")
    teaching_style: Optional[str] = None
    interest_category: Optional[str] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def validate_note_difficulty_update(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)

    @field_validator("teaching_style", mode="before")
    @classmethod
    def validate_teaching_style_update(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = str(v).strip().lower()
        if s not in _TEACHING_STYLES:
            raise ValueError(
                "teaching_style must be one of: conceptual, practical, "
                "exam-oriented, visual"
            )
        return s

    @field_validator("interest_category", mode="before")
    @classmethod
    def validate_interest_category_update(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        s = str(v).strip().lower()
        if s not in _INTEREST_CATEGORIES:
            raise ValueError(
                "interest_category must be one of: general, real-life, "
                "advanced, fun"
            )
        return s


class TopicNoteOut(BaseModel):
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


class OverrideQuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=3, max_length=5000)


class QuestionPayloadBase(BaseModel):
    question_text: str = Field(..., min_length=3, max_length=5000)
    options: List[str] = Field(default_factory=list, max_length=10)
    correct_answer: Optional[str] = Field(default=None, max_length=2000)
    explanation: str = Field(default="", max_length=5000)
    difficulty_level: str = Field(default="medium")
    question_type: Optional[Literal["mcq", "fill_in_blank", "descriptive"]] = None
    quiz_stage: Optional[Literal["concept_check", "cluster_quiz"]] = None

    @field_validator("difficulty_level", mode="before")
    @classmethod
    def validate_question_difficulty(cls, v: object) -> str:
        return parse_content_difficulty_strict(v)

    @field_validator("question_type", mode="before")
    @classmethod
    def normalize_question_type(cls, v: object) -> str | None:
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
    def normalize_quiz_stage(cls, v: object) -> str | None:
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
    def normalize_options(cls, v: object) -> list[str]:
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
    def normalize_correct_answer(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @model_validator(mode="after")
    def validate_question_shape(self) -> "QuestionPayloadBase":
        from app.services.handlers.concept_check_question_types import has_blank_marker

        if len(self.options) == 0:
            if has_blank_marker(self.question_text) and (self.correct_answer or "").strip():
                return self
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


class CreateQuestionRequest(QuestionPayloadBase):
    topic_id: str = Field(..., min_length=24, max_length=24)
    concept: Optional[str] = None
    concept_id: Optional[str] = Field(default=None, min_length=24, max_length=24)
    structured: bool = Field(default=False)

    @model_validator(mode="after")
    def require_quiz_stage_for_structured(self) -> "CreateQuestionRequest":
        if (self.concept_id or self.structured) and not self.quiz_stage:
            raise ValueError(
                "quiz_stage is required when concept_id is set or structured=true"
            )
        return self


class UpdateQuestionRequest(QuestionPayloadBase):
    pass


class TopicQuestionOut(BaseModel):
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


def _note_to_out(note: TopicNote) -> TopicNoteOut:
    return TopicNoteOut(
        id=str(note.id),
        topic_id=str(note.topic_id),
        concept=note.concept,
        concept_id=str(note.concept_id) if note.concept_id else None,
        concept_source=note.concept_source,
        content=note.content_markdown,
        note_type=note.note_type,
        difficulty_level=difficulty_for_json(note.difficulty_level),
        teaching_style=note.teaching_style,
        interest_category=note.interest_category,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _question_to_out(q: TopicQuestionBank) -> TopicQuestionOut:
    return TopicQuestionOut(
        id=str(q.id),
        topic_id=str(q.topic_id),
        concept=q.concept,
        concept_id=str(q.concept_id) if q.concept_id else None,
        concept_source=q.concept_source,
        content=q.question_text,
        options=list(q.options or []),
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        difficulty_level=difficulty_for_json(q.difficulty_level),
        question_type=getattr(q, "question_type", None),
        quiz_stage=getattr(q, "quiz_stage", None),
        created_at=q.created_at,
        updated_at=q.updated_at,
    )


async def _resolve_grade_board_for_note(
    organization_id: PydanticObjectId,
    class_id: str | None,
    curriculum_topic: Topic | None,
) -> tuple[str, str]:
    """Grade from org class name when possible; board defaults to general."""
    board = "general"
    org = await Organization.get(organization_id)
    if class_id and org is not None:
        cid = class_id.strip()
        for c in org.classes or []:
            if c.id == cid:
                name = (c.name or "").strip()
                if name:
                    return name[:32], board
                break
    if curriculum_topic is not None:
        depth = (getattr(curriculum_topic, "default_depth", None) or "").strip()
        if depth:
            return depth[:32], board
    return "General", board


async def _topic_in_org(
    topic_id: PydanticObjectId,
    organization_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic:
    topic = await topic_repository.get_by_id(topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )
    if topic.organization_id is not None and topic.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Topic does not belong to your organization",
        )
    return topic


def _can_access_teacher_topic_row(tt: TeacherTopic, user: User) -> bool:
    if user.organization_id is None or tt.organization_id != user.organization_id:
        return False
    if user.role in ("organization", "admin"):
        return True
    return tt.teacher_id == user.id


async def _assert_topic_parent_for_content_write(
    topic_id: PydanticObjectId,
    user: User,
    topic_repository: TopicRepository,
) -> None:
    """Allow parent to be a curriculum Topic or a TeacherTopic row."""
    tt = await TeacherTopic.get(topic_id)
    if tt is not None:
        if not _can_access_teacher_topic_row(tt, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed for this teacher topic",
            )
        return
    await _topic_in_org(topic_id, user.organization_id, topic_repository)


def _can_read_note_for_override(note: TopicNote, user: User) -> bool:
    if user.organization_id is None:
        return False
    if note.organization_id is None:
        return True
    return note.organization_id == user.organization_id


@router.post("/topic-note", response_model=IdResponse)
async def create_topic_note(
    body: CreateTopicNoteRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    note_repository: TopicNoteRepository = Depends(get_topic_note_repository),
) -> IdResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        tid = PydanticObjectId(body.topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    tt = await TeacherTopic.get(tid)
    if tt is not None:
        if not _can_access_teacher_topic_row(tt, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to add content to this teacher topic",
            )
        schema_version = getattr(tt, "curriculum_schema_version", "v1") or "v1"
        link = await ContentConceptLinkService().resolve_for_authoring(
            curriculum_schema_version=schema_version,
            topic_id=tid,
            topic_source="teacher",
            organization_id=current_user.organization_id,
            concept_id=body.concept_id,
            concept=body.concept,
            is_structured_flow=body.structured,
            teacher_topic=tt,
        )
        grade, board = await _resolve_grade_board_for_note(
            current_user.organization_id, tt.class_id, None
        )
        note = await note_repository.create(
            {
                "organization_id": current_user.organization_id,
                "topic_id": tid,
                "grade": grade,
                "board": board,
                "note_type": body.note_type,
                "content_markdown": body.content_markdown,
                "source_type": "teacher",
                "teaching_style": body.teaching_style,
                "interest_category": body.interest_category,
                "difficulty_level": body.difficulty_level,
                "approved": True,
                "usage_count": 0,
                "concept": link.concept,
                "concept_id": link.concept_id,
                "concept_source": link.concept_source,
            }
        )
        return IdResponse(id=str(note.id))

    topic = await _topic_in_org(tid, current_user.organization_id, topic_repository)
    schema_version = getattr(topic, "curriculum_schema_version", "v1") or "v1"
    link = await ContentConceptLinkService().resolve_for_authoring(
        curriculum_schema_version=schema_version,
        topic_id=tid,
        topic_source="catalog",
        organization_id=current_user.organization_id,
        concept_id=body.concept_id,
        concept=body.concept,
        is_structured_flow=body.structured,
        topic=topic,
    )
    grade, board = await _resolve_grade_board_for_note(
        current_user.organization_id, None, topic
    )
    note = await note_repository.create(
        {
            "organization_id": current_user.organization_id,
            "topic_id": tid,
            "grade": grade,
            "board": board,
            "note_type": body.note_type,
            "content_markdown": body.content_markdown,
            "source_type": "teacher",
            "teaching_style": body.teaching_style,
            "interest_category": body.interest_category,
            "difficulty_level": body.difficulty_level,
            "approved": True,
            "usage_count": 0,
            "concept": link.concept,
            "concept_id": link.concept_id,
            "concept_source": link.concept_source,
        }
    )
    return IdResponse(id=str(note.id))


@router.get("/topic-notes", response_model=List[TopicNoteOut])
async def list_topic_notes(
    topic_id: str = Query(..., min_length=24, max_length=24),
    concept: str = Query(..., min_length=1, max_length=500),
    current_user: User = Depends(get_current_teacher_or_admin),
    note_repository: TopicNoteRepository = Depends(get_topic_note_repository),
) -> List[TopicNoteOut]:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")
    normalized_concept = normalize_concept_filter(concept)
    if normalized_concept is None:
        raise HTTPException(status_code=400, detail="Invalid concept")
    tt = await TeacherTopic.get(tid)
    if tt is not None:
        if not _can_access_teacher_topic_row(tt, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to read this teacher topic",
            )
        rows = await note_repository.get_org_notes_for_concept(
            topic_id=tid,
            concept=normalized_concept,
            organization_id=current_user.organization_id,
        )
        return [_note_to_out(n) for n in rows]

    await _topic_in_org(tid, current_user.organization_id, topic_repository)
    rows = await note_repository.get_org_notes_for_concept(
        topic_id=tid,
        concept=normalized_concept,
        organization_id=current_user.organization_id,
    )
    return [_note_to_out(n) for n in rows]


@router.put("/topic-note/{note_id}", response_model=TopicNoteOut)
async def update_topic_note(
    note_id: str,
    body: UpdateTopicNoteRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> TopicNoteOut:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        nid = PydanticObjectId(note_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note_id")
    note = await TopicNote.get(nid)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    if note.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to update this note",
        )
    note.content_markdown = body.content_markdown
    note.note_type = body.note_type
    note.difficulty_level = body.difficulty_level
    note.teaching_style = body.teaching_style
    note.interest_category = body.interest_category
    note.updated_at = datetime.utcnow()
    await note.save()
    return _note_to_out(note)


@router.delete(
    "/topic-note/{note_id}",
    response_model=DeleteSuccessResponse,
)
async def delete_topic_note(
    note_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> DeleteSuccessResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        nid = PydanticObjectId(note_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note_id")
    note = await TopicNote.get(nid)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    if note.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to delete this note",
        )
    await note.delete()
    return DeleteSuccessResponse()


@router.post("/topic-note/{note_id}/override", response_model=IdResponse)
async def override_topic_note(
    note_id: str,
    body: OverrideTopicNoteRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    note_repository: TopicNoteRepository = Depends(get_topic_note_repository),
) -> IdResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        nid = PydanticObjectId(note_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note_id")
    old = await TopicNote.get(nid)
    if old is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    if not _can_read_note_for_override(old, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to override this note",
        )
    await _assert_topic_parent_for_content_write(
        old.topic_id, current_user, topic_repository
    )
    new_note = await note_repository.create(
        {
            "organization_id": current_user.organization_id,
            "topic_id": old.topic_id,
            "grade": old.grade,
            "board": old.board,
            "note_type": old.note_type,
            "content_markdown": body.content_markdown,
            "source_type": "teacher_override",
            "teaching_style": old.teaching_style,
            "interest_category": old.interest_category,
            "difficulty_level": old.difficulty_level,
            "approved": True,
            "usage_count": 0,
            "concept": old.concept,
            "concept_id": old.concept_id,
            "concept_source": old.concept_source,
            "content_version": getattr(old, "content_version", 1) or 1,
        }
    )
    return IdResponse(id=str(new_note.id))


async def _assert_stage_caps_for_concept_id(
    concept_id: PydanticObjectId | None,
    *,
    quiz_stage: str | None,
    question_type: str | None,
    exclude_question_id: PydanticObjectId | None = None,
) -> None:
    if quiz_stage is None or concept_id is None:
        return
    from app.models.curriculum.curriculum_concept import CurriculumConcept
    from app.services.curriculum.question_bank_stage_service import assert_quiz_stage_caps

    concept = await CurriculumConcept.get(concept_id)
    if concept is None or concept.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="concept_id is required for staged quiz questions",
        )
    await assert_quiz_stage_caps(
        concept=concept,
        quiz_stage=quiz_stage,
        question_type=question_type,
        exclude_question_id=exclude_question_id,
    )


def _inferred_type_from_payload(
    question_text: str,
    options: list[str],
    correct_answer: str | None,
    question_type: str | None,
) -> str | None:
    if question_type:
        return question_type
    from app.services.handlers.concept_check_question_types import has_blank_marker

    if len(options) >= 2:
        return "mcq"
    if has_blank_marker(question_text) and (correct_answer or "").strip():
        return "fill_in_blank"
    if (correct_answer or "").strip() or question_text:
        return "descriptive"
    return None


@router.post("/question", response_model=IdResponse)
async def create_question(
    body: CreateQuestionRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    question_repository: TopicQuestionRepository = Depends(
        get_topic_question_repository
    ),
) -> IdResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        tid = PydanticObjectId(body.topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")

    inferred_type = _inferred_type_from_payload(
        body.question_text,
        list(body.options or []),
        body.correct_answer,
        body.question_type,
    )

    tt = await TeacherTopic.get(tid)
    if tt is not None:
        if not _can_access_teacher_topic_row(tt, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to add questions to this teacher topic",
            )
        schema_version = getattr(tt, "curriculum_schema_version", "v1") or "v1"
        link = await ContentConceptLinkService().resolve_for_authoring(
            curriculum_schema_version=schema_version,
            topic_id=tid,
            topic_source="teacher",
            organization_id=current_user.organization_id,
            concept_id=body.concept_id,
            concept=body.concept,
            is_structured_flow=body.structured,
            teacher_topic=tt,
        )
        await _assert_stage_caps_for_concept_id(
            link.concept_id,
            quiz_stage=body.quiz_stage,
            question_type=inferred_type,
        )
        q = await question_repository.create(
            {
                "organization_id": current_user.organization_id,
                "topic_id": tid,
                "difficulty_level": body.difficulty_level,
                "question_text": body.question_text,
                "options": list(body.options or []),
                "correct_answer": body.correct_answer,
                "explanation": body.explanation,
                "source_type": "teacher",
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

    topic = await _topic_in_org(tid, current_user.organization_id, topic_repository)
    schema_version = getattr(topic, "curriculum_schema_version", "v1") or "v1"
    link = await ContentConceptLinkService().resolve_for_authoring(
        curriculum_schema_version=schema_version,
        topic_id=tid,
        topic_source="catalog",
        organization_id=current_user.organization_id,
        concept_id=body.concept_id,
        concept=body.concept,
        is_structured_flow=body.structured,
        topic=topic,
    )
    await _assert_stage_caps_for_concept_id(
        link.concept_id,
        quiz_stage=body.quiz_stage,
        question_type=inferred_type,
    )
    q = await question_repository.create(
        {
            "organization_id": current_user.organization_id,
            "topic_id": tid,
            "difficulty_level": body.difficulty_level,
            "question_text": body.question_text,
            "options": list(body.options or []),
            "correct_answer": body.correct_answer,
            "explanation": body.explanation,
            "source_type": "teacher",
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


def _can_read_question_for_override(q: TopicQuestionBank, user: User) -> bool:
    if user.organization_id is None:
        return False
    if q.organization_id is None:
        return True
    return q.organization_id == user.organization_id


@router.put("/question/{question_id}", response_model=TopicQuestionOut)
async def update_question(
    question_id: str,
    body: UpdateQuestionRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> TopicQuestionOut:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        qid = PydanticObjectId(question_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    row = await TopicQuestionBank.get(qid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )
    if row.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to update this question",
        )
    inferred_type = _inferred_type_from_payload(
        body.question_text,
        list(body.options or []),
        body.correct_answer,
        body.question_type,
    )
    stage = body.quiz_stage if body.quiz_stage is not None else getattr(row, "quiz_stage", None)
    if row.concept_id is not None and not stage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="quiz_stage is required for concept-linked questions",
        )
    await _assert_stage_caps_for_concept_id(
        row.concept_id,
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
    row.updated_at = datetime.utcnow()
    await row.save()
    return _question_to_out(row)


@router.delete(
    "/question/{question_id}",
    response_model=DeleteSuccessResponse,
)
async def delete_question(
    question_id: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> DeleteSuccessResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        qid = PydanticObjectId(question_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    row = await TopicQuestionBank.get(qid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )
    if row.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to delete this question",
        )
    await row.delete()
    return DeleteSuccessResponse()


@router.post("/question/{question_id}/override", response_model=IdResponse)
async def override_question(
    question_id: str,
    body: OverrideQuestionRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    question_repository: TopicQuestionRepository = Depends(
        get_topic_question_repository
    ),
) -> IdResponse:
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must belong to an organization",
        )
    try:
        qid = PydanticObjectId(question_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    old = await TopicQuestionBank.get(qid)
    if old is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )
    if not _can_read_question_for_override(old, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to override this question",
        )
    await _assert_topic_parent_for_content_write(
        old.topic_id, current_user, topic_repository
    )
    new_q = await question_repository.create(
        {
            "organization_id": current_user.organization_id,
            "topic_id": old.topic_id,
            "difficulty_level": old.difficulty_level,
            "question_text": body.question_text,
            "options": list(old.options or []),
            "correct_answer": old.correct_answer,
            "explanation": old.explanation,
            "source_type": "teacher_override",
            "approved": True,
            "usage_count": 0,
            "concept": old.concept,
            "concept_id": old.concept_id,
            "concept_source": old.concept_source,
        }
    )
    return IdResponse(id=str(new_q.id))
