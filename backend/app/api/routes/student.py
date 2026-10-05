"""Student-specific endpoints (profile, institution-scoped subject topics)."""

from __future__ import annotations

import logging
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.models.curriculum.subjects import Subject
from app.models.identification.student_profiles import StudentProfile
from app.models.identification.users import User
from app.models.organization import OrgItem, Organization
from app.models.teacher_topic import TeacherTopic
from app.repositories.mastery_repository import MasteryRepository, get_mastery_repository
from app.repositories.topic_repository import TopicRepository, get_topic_repository
from app.services.language.tutor_language_policy import resolve_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/student", tags=["Student"])


class StudentProfileOut(BaseModel):
    class_id: Optional[str] = None
    grade: str = ""
    preferred_language: str = "en"


class StudentProfileUpdateRequest(BaseModel):
    """Learner-editable preferences. Only provided fields are applied."""

    preferred_language: Optional[Literal["en", "hinglish"]] = Field(default=None)


class TopicOut(BaseModel):
    """Institution: id is TeacherTopic id. Personal/non-institution: curriculum Topic id."""

    id: str
    topic_name: str
    topic_description: str = ""
    difficulty_level: str = "medium"
    mastery_score: float | None = None
    is_teacher: bool = True


def _find_org_subject(
    org: Organization, class_id: Optional[str], subject_id: str
) -> Optional[OrgItem]:
    sid = subject_id.strip()
    for c in org.classes or []:
        if class_id and c.id != class_id:
            continue
        for s in c.subjects or []:
            if s.id == sid:
                return s
    return None


def _public_language(raw: Optional[str]) -> str:
    """Expose only the two supported tutor languages; legacy codes read as English."""
    return "hinglish" if resolve_mode(raw) == "hinglish" else "en"


def _find_org_subject_any_class(org: Organization, subject_id: str) -> Optional[OrgItem]:
    sid = subject_id.strip()
    for c in org.classes or []:
        for s in c.subjects or []:
            if s.id == sid:
                return s
    return None


@router.get("/profile", response_model=StudentProfileOut)
async def get_student_profile(current_user: User = Depends(get_current_user)) -> StudentProfileOut:
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access only",
        )
    if current_user.organization_id is None:
        return StudentProfileOut(class_id=None, grade="")
    profile = await StudentProfile.find_one(
        {"organization_id": current_user.organization_id, "user_id": current_user.id}
    )
    if profile is None:
        return StudentProfileOut(class_id=None, grade="")
    cid = (profile.class_id or "").strip() or None
    return StudentProfileOut(
        class_id=cid,
        grade=profile.grade or "",
        preferred_language=_public_language(profile.preferred_language),
    )


@router.patch("/profile", response_model=StudentProfileOut)
async def update_student_profile(
    payload: StudentProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> StudentProfileOut:
    """Update learner preferences. Applies to the next tutor response (no restart)."""
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access only",
        )
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    profile = await StudentProfile.find_one(
        {"organization_id": current_user.organization_id, "user_id": current_user.id}
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )

    if payload.preferred_language is not None:
        profile.preferred_language = payload.preferred_language
        await profile.save()

    cid = (profile.class_id or "").strip() or None
    return StudentProfileOut(
        class_id=cid,
        grade=profile.grade or "",
        preferred_language=_public_language(profile.preferred_language),
    )


@router.get("/subjects/{subject_id}/topics", response_model=List[TopicOut])
async def list_student_subject_topics(
    subject_id: str,
    current_user: User = Depends(get_current_user),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
) -> List[TopicOut]:
    """
    - **Institution** orgs: ``subject_id`` is the org-structure subject id; topics are **TeacherTopic** rows.
    - **Non-institution** (e.g. personal): ``subject_id`` is the curriculum **Subject** Mongo id; topics come
      from the curriculum **Topic** collection (same behavior as ``GET /curriculum/subjects/{id}/topics``).
    """
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student access only",
        )
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )

    org = await Organization.get(current_user.organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if org.organization_type != "institution":
        try:
            sid = PydanticObjectId(subject_id.strip())
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject_id")

        subject = await Subject.get(sid)
        if subject is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
        uid = current_user.organization_id
        if subject.organization_id is not None and subject.organization_id != uid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

        topics = await topic_repository.get_topics_by_subject(sid, limit=200)
        out_curriculum: List[TopicOut] = []
        for t in topics:
            if not getattr(t, "is_active", True):
                continue
            rec = await mastery_repository.get_topic_mastery(
                current_user.id,
                t.id,
                organization_id=current_user.organization_id,
                concept=None,
            )
            score = float(rec.mastery_score) if rec is not None else None
            desc = t.topic_description[:280] + ("…" if len(t.topic_description) > 280 else "")
            out_curriculum.append(
                TopicOut(
                    id=str(t.id),
                    topic_name=t.topic_name,
                    topic_description=desc,
                    difficulty_level=t.difficulty_level,
                    mastery_score=score,
                    is_teacher=False,
                )
            )
        out_curriculum.sort(key=lambda x: x.topic_name.lower())
        return out_curriculum

    org_subject_id = subject_id.strip()

    profile = await StudentProfile.find_one(
        {"organization_id": current_user.organization_id, "user_id": current_user.id}
    )
    class_id = (profile.class_id or "").strip() if profile else ""
    class_id = class_id or None

    org_item = None
    if class_id:
        org_item = _find_org_subject(org, class_id, org_subject_id)
    if org_item is None:
        org_item = _find_org_subject_any_class(org, org_subject_id)
    if org_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    effective_class_id: Optional[str] = class_id
    if effective_class_id is None:
        for c in org.classes or []:
            for s in c.subjects or []:
                if s.id == org_subject_id:
                    effective_class_id = c.id
                    break
            if effective_class_id:
                break

    trows: List[TeacherTopic] = []
    if effective_class_id:
        trows = await TeacherTopic.find(
            TeacherTopic.organization_id == current_user.organization_id,
            TeacherTopic.class_id == effective_class_id,
            TeacherTopic.subject_id == org_subject_id,
        ).to_list()

    logger.info(
        "[student/topics] debug class_id=%s org_subject_id=%s teacher_topics_count=%s",
        effective_class_id,
        org_subject_id,
        len(trows),
    )

    if not trows:
        logger.warning(
            "[student/topics] no TeacherTopic rows for class_id=%s org_subject_id=%s; returning []",
            effective_class_id,
            org_subject_id,
        )
        return []

    out: List[TopicOut] = []
    for tt in trows:
        rec = await mastery_repository.get_topic_mastery(
            current_user.id,
            tt.id,
            organization_id=current_user.organization_id,
            concept=None,
        )
        score = float(rec.mastery_score) if rec is not None else None
        out.append(
            TopicOut(
                id=str(tt.id),
                topic_name=tt.topic_name,
                topic_description="",
                difficulty_level="medium",
                mastery_score=score,
                is_teacher=True,
            )
        )
    out.sort(key=lambda x: x.topic_name.lower())
    return out
