"""Curriculum listing: subjects and topics with mastery for the current student."""

from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.models.curriculum.subjects import Subject
from app.models.curriculum.topics import Topic
from app.models.identification.student_profiles import StudentProfile
from app.models.identification.users import User
from app.repositories.mastery_repository import MasteryRepository, get_mastery_repository
from app.repositories.topic_repository import TopicRepository, get_topic_repository
from app.services.classroom.class_session_plan_service import ClassSessionPlanService

router = APIRouter(prefix="/curriculum", tags=["Curriculum"])


def _normalize_grade_for_match(value: str | None) -> str:
    """Case-insensitive grade comparison; strips optional ``Grade `` prefix."""
    if not value:
        return ""
    s = value.strip().lower()
    if s.startswith("grade "):
        s = s[6:].strip()
    return s


class SubjectOut(BaseModel):
    id: str
    name: str
    description: str
    grade: str
    board: str


class SubjectCatalogOut(BaseModel):
    """Minimal subject row for admin linking UI."""

    id: str
    name: str


class TopicOut(BaseModel):
    id: str
    topic_name: str
    topic_description: str
    difficulty_level: str
    mastery_score: float | None = Field(
        default=None,
        description="Topic-level mastery 0–100, or null if not yet assessed",
    )


class DashboardOut(BaseModel):
    overall_mastery: float
    topics_practiced: int
    recent_topics: List[TopicOut]


@router.get("/subjects", response_model=List[SubjectOut])
async def list_subjects(
    current_user: User = Depends(get_current_user),
) -> List[SubjectOut]:
    """Active subjects: tenant-owned plus global catalog for non-students; students see global catalog for their grade only."""
    if current_user.role == "student":
        if current_user.organization_id is None:
            return []
        profile = await StudentProfile.find_one(
            {
                "organization_id": current_user.organization_id,
                "user_id": current_user.id,
            }
        )
        if profile is None:
            return []
        want = _normalize_grade_for_match(profile.grade)
        if not want:
            return []
        subject_filter: dict = {
            "organization_id": None,
            "is_active": True,
            "status": "active",
        }
        subjects = await Subject.find(subject_filter).sort([("name", 1)]).to_list()
        subjects = [
            s for s in subjects if _normalize_grade_for_match(s.grade) == want
        ]
        return [
            SubjectOut(
                id=str(s.id),
                name=s.name,
                description=s.description,
                grade=s.grade,
                board=s.board,
            )
            for s in subjects
        ]

    org_id = current_user.organization_id
    if org_id is None:
        subject_filter = {
            "organization_id": None,
            "is_active": True,
            "status": "active",
        }
    else:
        subject_filter = {
            "is_active": True,
            "status": "active",
            "$or": [
                {"organization_id": org_id},
                {"organization_id": None},
            ],
        }
    subjects = await Subject.find(subject_filter).sort([("name", 1)]).to_list()
    return [
        SubjectOut(
            id=str(s.id),
            name=s.name,
            description=s.description,
            grade=s.grade,
            board=s.board,
        )
        for s in subjects
    ]


@router.get("/subjects/catalog", response_model=List[SubjectCatalogOut])
async def list_subjects_catalog(
    current_user: User = Depends(get_current_user),
) -> List[SubjectCatalogOut]:
    """Active curriculum subjects (id + name only) for org-scoped admin UIs."""
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    oid = current_user.organization_id
    subjects = await Subject.find(
        {
            "is_active": True,
            "status": "active",
            "$or": [
                {"organization_id": oid},
                {"organization_id": None},
            ],
        }
    ).sort([("name", 1)]).to_list()
    return [SubjectCatalogOut(id=str(s.id), name=s.name) for s in subjects]


@router.get("/subjects/{subject_id}/topics", response_model=List[TopicOut])
async def list_topics_with_mastery(
    subject_id: str,
    current_user: User = Depends(get_current_user),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
) -> List[TopicOut]:
    """Topics for a subject with topic-level mastery for the current user."""
    try:
        sid = PydanticObjectId(subject_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject_id")

    subject = await Subject.get(sid)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    uid = current_user.organization_id
    if subject.organization_id is not None and subject.organization_id != uid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    topics = await topic_repository.get_topics_by_subject(sid, limit=200)
    out: List[TopicOut] = []
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
        out.append(
            TopicOut(
                id=str(t.id),
                topic_name=t.topic_name,
                topic_description=t.topic_description[:280]
                + ("…" if len(t.topic_description) > 280 else ""),
                difficulty_level=t.difficulty_level,
                mastery_score=score,
            )
        )
    out.sort(key=lambda x: x.topic_name.lower())
    return out


class SuggestedCatalogTopicOut(BaseModel):
    id: str
    topic_name: str
    key_concepts: List[str]


@router.get(
    "/suggested-catalog-topics",
    response_model=List[SuggestedCatalogTopicOut],
)
async def suggested_catalog_topics(
    curriculum_subject_id: Optional[str] = Query(
        default=None,
        description="Preferred: Mongo id of a curriculum Subject in your org",
    ),
    subject_name: Optional[str] = Query(
        default=None,
        max_length=200,
        description="Legacy: match curriculum subject by display name (case-insensitive)",
    ),
    current_user: User = Depends(get_current_teacher_or_admin),
) -> List[SuggestedCatalogTopicOut]:
    """
    Catalog topics under a curriculum subject. Prefer ``curriculum_subject_id``;
    ``subject_name`` is retained for backward compatibility.
    """
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    match: Subject | None = None
    cs_raw = (curriculum_subject_id or "").strip()
    if cs_raw:
        try:
            sid = PydanticObjectId(cs_raw)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid curriculum_subject_id",
            ) from None
        cand = await Subject.get(sid)
        if cand is not None and (
            cand.organization_id is None
            or cand.organization_id == current_user.organization_id
        ):
            match = cand
    elif subject_name and subject_name.strip():
        key = subject_name.strip().lower()
        oid = current_user.organization_id
        subjects = await Subject.find(
            {
                "is_active": True,
                "status": "active",
                "$or": [
                    {"organization_id": oid},
                    {"organization_id": None},
                ],
            }
        ).to_list()
        match = next(
            (s for s in subjects if s.name.strip().lower() == key),
            None,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide curriculum_subject_id or subject_name",
        )
    if match is None:
        return []
    topics = await Topic.find(
        {
            "subject_id": match.id,
            "is_active": True,
            "status": "active",
        }
    ).sort([("topic_name", 1)]).to_list()
    return [
        SuggestedCatalogTopicOut(
            id=str(t.id),
            topic_name=t.topic_name,
            key_concepts=list(t.key_concepts or []),
        )
        for t in topics
    ]


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard_summary(
    current_user: User = Depends(get_current_user),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> DashboardOut:
    """Aggregate mastery and recent topic activity for the dashboard."""
    records = await mastery_repository.get_student_mastery(
        current_user.id,
        organization_id=current_user.organization_id,
        limit=500,
    )
    topic_level = [r for r in records if r.concept is None or r.concept == ""]
    if not topic_level:
        return DashboardOut(
            overall_mastery=0.0,
            topics_practiced=0,
            recent_topics=[],
        )

    scores = [float(r.mastery_score) for r in topic_level]
    overall = sum(scores) / len(scores)
    recent_sorted = sorted(
        topic_level,
        key=lambda r: r.last_updated,
        reverse=True,
    )[:8]
    recent_topics: List[TopicOut] = []
    for r in recent_sorted:
        topic = await topic_repository.get_by_id(r.topic_id)
        if topic is None:
            continue
        recent_topics.append(
            TopicOut(
                id=str(topic.id),
                topic_name=topic.topic_name,
                topic_description=topic.topic_description[:280]
                + ("…" if len(topic.topic_description) > 280 else ""),
                difficulty_level=topic.difficulty_level,
                mastery_score=float(r.mastery_score),
            )
        )
    return DashboardOut(
        overall_mastery=round(overall, 1),
        topics_practiced=len(topic_level),
        recent_topics=recent_topics,
    )


class CatalogSessionPlanSummary(BaseModel):
    id: str
    sequence_number: int
    title: str
    description: str
    target_duration_minutes: Optional[int] = None


@router.get(
    "/topics/{topic_id}/session-plans",
    response_model=list[CatalogSessionPlanSummary],
)
async def list_catalog_session_plans_for_students(
    topic_id: str,
    current_user: User = Depends(get_current_user),
) -> list[CatalogSessionPlanSummary]:
    """Published catalog session plans for independent-student topic launch."""
    try:
        tid = PydanticObjectId(topic_id.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id") from None

    topic = await Topic.get(tid)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.curriculum_schema_version != "v2" or topic.curriculum_published_at is None:
        return []

    plans = await ClassSessionPlanService().list_published_catalog_plans_for_students(
        catalog_topic_id=tid,
    )
    return [
        CatalogSessionPlanSummary(
            id=str(p.id),
            sequence_number=p.sequence_number,
            title=p.title,
            description=p.description,
            target_duration_minutes=p.target_duration_minutes,
        )
        for p in plans
    ]
