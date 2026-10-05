from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.responses import Response
from pydantic import BaseModel, Field, field_validator

from app.api.schemas.learning_graph import (
    CreatePrerequisiteRequest,
    CreateProgressionRequest,
    PrerequisiteEdgeOut,
    ProgressionEdgeOut,
)
from app.core.dependencies import get_current_teacher_or_admin
from app.models.identification.users import User
from app.models.teacher_topic import TeacherTopic
from app.repositories.topic_repository import TopicRepository, get_topic_repository
from app.services.curriculum_preview_service import (
    build_teacher_curriculum_preview,
    import_catalog_teacher_topics,
)
from app.services import learning_graph_service as learning_graph_svc
from app.services.teacher_topic_service import (
    assert_class_subject_allowed,
    assert_curriculum_topic_allowed_for_teacher_row,
    assert_no_duplicate_topic_name,
    get_topic_for_mutation,
    load_org,
    normalize_ordered_unique_concepts,
    normalize_topic_name,
    validate_concept_clusters,
)

router = APIRouter(prefix="/teacher", tags=["Teacher curriculum"])


class CreateTeacherTopicBody(BaseModel):
    class_id: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=64)
    topic_name: str = Field(..., min_length=1, max_length=500)
    curriculum_topic_id: Optional[str] = None

    @field_validator("curriculum_topic_id")
    @classmethod
    def validate_curriculum_topic_id(
        cls, v: Optional[str]
    ) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        s = str(v).strip()
        if len(s) != 24:
            raise ValueError(
                "curriculum_topic_id must be a 24-character ObjectId string"
            )
        return s


class LinkCurriculumTopicBody(BaseModel):
    curriculum_topic_id: str = Field(..., min_length=24, max_length=24)


class AddConceptsBody(BaseModel):
    concepts: List[str] = Field(default_factory=list)
    concept_clusters: Optional[List[List[str]]] = Field(
        default=None,
        description=(
            "Optional explicit grouping of concepts into clusters. "
            "Every concept must exist in `concepts`; no duplicates across clusters. "
            "Omit (or pass null) to reset clusters — auto-derivation will be used."
        ),
    )


class UpdateTeacherTopicBody(BaseModel):
    topic_name: str = Field(..., min_length=1, max_length=500)


class TeacherTopicOut(BaseModel):
    id: str
    class_id: str
    subject_id: str
    topic_name: str
    key_concepts: List[str]
    concept_clusters: Optional[List[List[str]]] = None
    curriculum_topic_id: Optional[str] = None


def _to_out(doc: TeacherTopic) -> TeacherTopicOut:
    return TeacherTopicOut(
        id=str(doc.id),
        class_id=doc.class_id,
        subject_id=doc.subject_id,
        topic_name=doc.topic_name,
        key_concepts=list(doc.key_concepts or []),
        concept_clusters=doc.concept_clusters,
        curriculum_topic_id=(
            str(doc.curriculum_topic_id) if doc.curriculum_topic_id else None
        ),
    )


class CurriculumPreviewSampleNoteOut(BaseModel):
    concept: Optional[str] = None
    content_markdown: str = ""


class CurriculumPreviewSampleQuestionOut(BaseModel):
    question_text: str = ""
    options: List[str] = Field(default_factory=list)
    correct_answer: Optional[str] = None


class CurriculumPreviewTopicOut(BaseModel):
    name: str
    concept_count: int
    key_concepts: List[str] = Field(default_factory=list)
    sample_notes: List[CurriculumPreviewSampleNoteOut] = Field(default_factory=list)
    sample_questions: List[CurriculumPreviewSampleQuestionOut] = Field(
        default_factory=list
    )


class CurriculumPreviewSubjectOut(BaseModel):
    id: str
    name: str
    grade: str


class CurriculumPreviewResponse(BaseModel):
    found: bool
    message: Optional[str] = None
    subject: Optional[CurriculumPreviewSubjectOut] = None
    topics: List[CurriculumPreviewTopicOut] = Field(default_factory=list)


class ImportCurriculumBody(BaseModel):
    class_id: str = Field(..., min_length=1, max_length=64)
    subject_id: str = Field(..., min_length=1, max_length=64)


class ImportCurriculumResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
    imported_count: int = 0
    skipped_count: int = 0


@router.get("/curriculum-preview", response_model=CurriculumPreviewResponse)
async def teacher_curriculum_preview(
    class_id: str = Query(..., min_length=1, max_length=64),
    subject_id: str = Query(..., min_length=1, max_length=64),
    user: User = Depends(get_current_teacher_or_admin),
) -> CurriculumPreviewResponse:
    """
    Preview global catalog topics for an org class/subject before import.

    Grade is taken from the class name and matched strictly to catalog subjects; subject name is fuzzy-matched.
    """
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await load_org(user.organization_id)
    cid = class_id.strip()
    sid = subject_id.strip()
    assert_class_subject_allowed(user, cid, sid, org)

    raw = await build_teacher_curriculum_preview(org, cid, sid)
    if not raw.get("found"):
        return CurriculumPreviewResponse(
            found=False,
            message=raw.get("message") or "No curriculum found",
        )
    sub = raw.get("subject") or {}
    topic_rows = raw.get("topics") or []
    return CurriculumPreviewResponse(
        found=True,
        subject=CurriculumPreviewSubjectOut(
            id=sub["id"],
            name=sub["name"],
            grade=sub["grade"],
        ),
        topics=[
            CurriculumPreviewTopicOut(
                name=str(t.get("name") or ""),
                concept_count=int(t.get("concept_count") or 0),
                key_concepts=list(t.get("key_concepts") or []),
                sample_notes=[
                    CurriculumPreviewSampleNoteOut(
                        concept=n.get("concept"),
                        content_markdown=str(n.get("content_markdown") or ""),
                    )
                    for n in (t.get("sample_notes") or [])
                ],
                sample_questions=[
                    CurriculumPreviewSampleQuestionOut(
                        question_text=str(q.get("question_text") or ""),
                        options=list(q.get("options") or []),
                        correct_answer=q.get("correct_answer"),
                    )
                    for q in (t.get("sample_questions") or [])
                ],
            )
            for t in topic_rows
        ],
    )


@router.post("/import-curriculum", response_model=ImportCurriculumResponse)
async def import_teacher_curriculum(
    body: ImportCurriculumBody,
    user: User = Depends(get_current_teacher_or_admin),
) -> ImportCurriculumResponse:
    """
    Link the org class subject to the matched global catalog subject and create
    teacher topics (with catalog links and key concepts), skipping existing topic names.
    """
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await load_org(user.organization_id)
    cid = body.class_id.strip()
    sid = body.subject_id.strip()
    assert_class_subject_allowed(user, cid, sid, org)

    result = await import_catalog_teacher_topics(user, org, cid, sid)
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message") or "No curriculum found",
        )
    return ImportCurriculumResponse(
        success=True,
        imported_count=int(result.get("imported_count") or 0),
        skipped_count=int(result.get("skipped_count") or 0),
    )


@router.post("/topic", response_model=TeacherTopicOut)
async def create_teacher_topic(
    body: CreateTeacherTopicBody,
    user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> TeacherTopicOut:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await load_org(user.organization_id)
    class_id = body.class_id.strip()
    subject_id = body.subject_id.strip()
    topic_name = body.topic_name.strip()
    assert_class_subject_allowed(user, class_id, subject_id, org)

    await assert_no_duplicate_topic_name(
        user.organization_id,
        class_id,
        subject_id,
        topic_name,
    )

    ct_oid: Optional[PydanticObjectId] = None
    raw_ct = (body.curriculum_topic_id or "").strip()
    if raw_ct:
        try:
            ct_oid = PydanticObjectId(raw_ct)
        except Exception:
            raise HTTPException(
                status_code=400, detail="Invalid curriculum_topic_id"
            ) from None
        await assert_curriculum_topic_allowed_for_teacher_row(
            user,
            TeacherTopic(
                organization_id=user.organization_id,
                teacher_id=user.id,
                class_id=class_id,
                subject_id=subject_id,
                topic_name=normalize_topic_name(topic_name),
                key_concepts=[],
                curriculum_topic_id=None,
            ),
            ct_oid,
            topic_repository,
            org,
        )

    doc = TeacherTopic(
        organization_id=user.organization_id,
        teacher_id=user.id,
        class_id=class_id,
        subject_id=subject_id,
        topic_name=normalize_topic_name(topic_name),
        key_concepts=[],
        curriculum_topic_id=ct_oid,
    )
    await doc.insert()
    return _to_out(doc)


@router.patch("/topic/{topic_id}", response_model=TeacherTopicOut)
async def update_teacher_topic(
    topic_id: str,
    body: UpdateTeacherTopicBody,
    user: User = Depends(get_current_teacher_or_admin),
) -> TeacherTopicOut:
    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic id") from None

    topic = await get_topic_for_mutation(tid, user)
    org = await load_org(user.organization_id) if user.organization_id else None
    assert_class_subject_allowed(user, topic.class_id, topic.subject_id, org)

    new_name = body.topic_name.strip()
    await assert_no_duplicate_topic_name(
        user.organization_id,
        topic.class_id,
        topic.subject_id,
        new_name,
        exclude_topic_id=topic.id,
    )
    topic.topic_name = normalize_topic_name(new_name)
    await topic.save()
    return _to_out(topic)


@router.delete("/topic/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher_topic(
    topic_id: str,
    user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic id") from None

    topic = await get_topic_for_mutation(tid, user)
    org = await load_org(user.organization_id) if user.organization_id else None
    assert_class_subject_allowed(user, topic.class_id, topic.subject_id, org)
    await topic.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/topic/{topic_id}/link-curriculum", response_model=TeacherTopicOut)
async def link_teacher_topic_curriculum(
    topic_id: str,
    body: LinkCurriculumTopicBody,
    user: User = Depends(get_current_teacher_or_admin),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> TeacherTopicOut:
    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic id") from None
    try:
        ct_oid = PydanticObjectId(body.curriculum_topic_id.strip())
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid curriculum_topic_id"
        ) from None

    topic = await get_topic_for_mutation(tid, user)
    org = await load_org(user.organization_id) if user.organization_id else None
    assert_class_subject_allowed(user, topic.class_id, topic.subject_id, org)

    await assert_curriculum_topic_allowed_for_teacher_row(
        user, topic, ct_oid, topic_repository, org
    )
    topic.curriculum_topic_id = ct_oid
    await topic.save()
    return _to_out(topic)


@router.post("/topic/{topic_id}/concepts", response_model=TeacherTopicOut)
async def add_teacher_topic_concepts(
    topic_id: str,
    body: AddConceptsBody,
    user: User = Depends(get_current_teacher_or_admin),
) -> TeacherTopicOut:
    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic id") from None

    topic = await get_topic_for_mutation(tid, user)
    org = await load_org(user.organization_id) if user.organization_id else None
    assert_class_subject_allowed(user, topic.class_id, topic.subject_id, org)

    normalized = normalize_ordered_unique_concepts(body.concepts)

    # Validate clusters against the NEW normalized concept list.
    # If concept_clusters is omitted (None), reset to None so stale clusters
    # from a previous set of concepts don't remain.
    if body.concept_clusters is not None:
        try:
            validate_concept_clusters(normalized, body.concept_clusters)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    topic.key_concepts = normalized
    topic.concept_clusters = body.concept_clusters  # None = reset; explicit = validated
    await topic.save()
    return _to_out(topic)


@router.get("/topics", response_model=List[TeacherTopicOut])
async def list_teacher_topics(
    class_id: str = Query(..., min_length=1, max_length=64),
    subject_id: str = Query(..., min_length=1, max_length=64),
    user: User = Depends(get_current_teacher_or_admin),
) -> List[TeacherTopicOut]:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await load_org(user.organization_id)
    assert_class_subject_allowed(user, class_id, subject_id, org)

    q = {
        "organization_id": user.organization_id,
        "teacher_id": user.id,
        "class_id": class_id,
        "subject_id": subject_id,
    }
    items = await TeacherTopic.find(q).to_list()
    items.sort(key=lambda t: (t.topic_name or "").lower())
    return [_to_out(t) for t in items]


# --- Learning graph (tenant edges + fallback to global catalog edges) ---


def _require_teacher_org(user: User) -> PydanticObjectId:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    return user.organization_id


@router.post("/prerequisite", response_model=PrerequisiteEdgeOut)
async def teacher_create_prerequisite(
    body: CreatePrerequisiteRequest,
    user: User = Depends(get_current_teacher_or_admin),
) -> PrerequisiteEdgeOut:
    org_id = _require_teacher_org(user)
    tid = learning_graph_svc.parse_topic_oid(body.topic_id, "topic_id")
    pid = learning_graph_svc.parse_topic_oid(
        body.prerequisite_topic_id, "prerequisite_topic_id"
    )
    row = await learning_graph_svc.create_prerequisite_edge(
        topic_id=tid,
        prerequisite_topic_id=pid,
        organization_id=org_id,
        mode="teacher",
        user_org_id=org_id,
    )
    return PrerequisiteEdgeOut(
        id=str(row.id),
        topic_id=str(row.topic_id),
        prerequisite_topic_id=str(row.prerequisite_topic_id),
    )


@router.get("/prerequisites", response_model=List[PrerequisiteEdgeOut])
async def teacher_list_prerequisites(
    topic_id: str = Query(..., min_length=24, max_length=24),
    user: User = Depends(get_current_teacher_or_admin),
) -> List[PrerequisiteEdgeOut]:
    org_id = _require_teacher_org(user)
    t_oid = learning_graph_svc.parse_topic_oid(topic_id, "topic_id")
    rows = await learning_graph_svc.list_prerequisites_teacher_with_fallback(
        t_oid, org_id
    )
    return [PrerequisiteEdgeOut(**r) for r in rows]


@router.delete("/prerequisite/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def teacher_delete_prerequisite(
    edge_id: str,
    user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    org_id = _require_teacher_org(user)
    eid = learning_graph_svc.parse_topic_oid(edge_id, "edge_id")
    await learning_graph_svc.delete_prerequisite_teacher(eid, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/progression", response_model=ProgressionEdgeOut)
async def teacher_create_progression(
    body: CreateProgressionRequest,
    user: User = Depends(get_current_teacher_or_admin),
) -> ProgressionEdgeOut:
    org_id = _require_teacher_org(user)
    tid = learning_graph_svc.parse_topic_oid(body.topic_id, "topic_id")
    nid = learning_graph_svc.parse_topic_oid(
        body.recommended_next_topic_id, "recommended_next_topic_id"
    )
    row = await learning_graph_svc.create_progression_edge(
        topic_id=tid,
        recommended_next_topic_id=nid,
        minimum_mastery=float(body.minimum_mastery_to_recommend),
        organization_id=org_id,
        mode="teacher",
        user_org_id=org_id,
    )
    return ProgressionEdgeOut(
        id=str(row.id),
        topic_id=str(row.topic_id),
        recommended_next_topic_id=str(row.recommended_next_topic_id),
        minimum_mastery_to_recommend=int(
            round(float(row.minimum_mastery_to_recommend))
        ),
    )


@router.get("/progression", response_model=List[ProgressionEdgeOut])
async def teacher_list_progression(
    topic_id: str = Query(..., min_length=24, max_length=24),
    user: User = Depends(get_current_teacher_or_admin),
) -> List[ProgressionEdgeOut]:
    org_id = _require_teacher_org(user)
    t_oid = learning_graph_svc.parse_topic_oid(topic_id, "topic_id")
    rows = await learning_graph_svc.list_progression_teacher_with_fallback(
        t_oid, org_id
    )
    return [ProgressionEdgeOut(**r) for r in rows]


@router.delete("/progression/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def teacher_delete_progression(
    edge_id: str,
    user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    org_id = _require_teacher_org(user)
    eid = learning_graph_svc.parse_topic_oid(edge_id, "edge_id")
    await learning_graph_svc.delete_progression_teacher(eid, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
