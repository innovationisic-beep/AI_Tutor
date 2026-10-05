from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, cast

from beanie.operators import In
from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.models.identification.users import User
from app.models.identification.student_profiles import StudentProfile
from app.models.learning.session_assignments import SessionAssignment
from app.models.summaries.session_summaries import SessionSummary
from app.models.content.topic_notes import TopicNote
from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.repositories.event_repository import EventRepository, get_event_repository
from app.repositories.knowledge_gap_repository import (
    KnowledgeGapRepository,
    get_knowledge_gap_repository,
)
from app.repositories.mastery_repository import (
    MasteryRepository,
    get_mastery_repository,
)
from app.repositories.recommendation_repository import (
    RecommendationRepository,
    get_recommendation_repository,
)
from app.repositories.session_repository import SessionRepository, get_session_repository
from app.repositories.topic_progression_repository import (
    TopicProgressionRepository,
    get_topic_progression_repository,
)
from app.repositories.topic_repository import TopicRepository, get_topic_repository
from app.services.mastery_service import MasteryService
from app.services.recommendation_service import RecommendationService
from app.services.handlers.session_meta import build_teacher_session_meta
from app.services.handlers.text_only_reply import coerce_plain_text_reply
from app.services.session_service import SessionService
from app.services.classroom.class_session_plan_service import ClassSessionPlanService
from app.services.curriculum.topic_context_service import (
    topic_context_from_catalog_topic,
    topic_context_from_teacher_topic,
)
from app.services.runtime.curriculum_resolution_service import (
    CurriculumResolutionError,
    CurriculumResolutionService,
)
from app.models.runtime.runtime_curriculum_manifest import RuntimeCurriculumManifest

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _plan_progression_out(raw: dict[str, Any] | None) -> PlanProgressionOut | None:
    if not isinstance(raw, dict):
        return None
    path_raw = raw.get("learning_path")
    learning_path: list[LearningPathSessionOut] = []
    if isinstance(path_raw, list):
        for row in path_raw:
            if not isinstance(row, dict):
                continue
            learning_path.append(
                LearningPathSessionOut(
                    session_plan_id=str(row.get("session_plan_id") or ""),
                    sequence_number=int(row.get("sequence_number") or 0),
                    title=str(row.get("title") or ""),
                    state=cast(
                        Literal["completed", "active", "available", "locked"],
                        str(row.get("state") or "locked"),
                    ),
                )
            )
    return PlanProgressionOut(
        learning_path=learning_path,
        last_transition=(
            raw.get("last_transition")
            if isinstance(raw.get("last_transition"), dict)
            else None
        ),
        completion_percentage=float(raw.get("completion_percentage") or 0.0),
        status=str(raw.get("status") or "not_started"),
        resume_pointer=(
            raw.get("resume_pointer")
            if isinstance(raw.get("resume_pointer"), dict)
            else None
        ),
        transition=(
            raw.get("transition") if isinstance(raw.get("transition"), dict) else None
        ),
    )


async def _runtime_manifest_for_topic_start(
    topic: TeacherTopic | Topic,
) -> Optional[RuntimeCurriculumManifest]:
    if topic.curriculum_schema_version != "v2" or topic.curriculum_published_at is None:
        return None
    if isinstance(topic, TeacherTopic):
        ctx = await topic_context_from_teacher_topic(topic)
    else:
        ctx = await topic_context_from_catalog_topic(topic)
    try:
        return await CurriculumResolutionService().resolve_published_topic_v2(ctx)
    except CurriculumResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


class StartSessionRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    action: Optional[Literal["continue", "restart"]] = None
    curriculum_class_id: Optional[str] = Field(
        default=None, max_length=64, description="Org class id for TeacherTopic lookup"
    )
    curriculum_subject_id: Optional[str] = Field(
        default=None, max_length=64, description="Org subject id for TeacherTopic lookup"
    )
    catalog_session_plan_id: Optional[str] = Field(
        default=None,
        min_length=24,
        max_length=24,
        description="Published catalog session plan for independent-student scoped launch",
    )


class EndSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=24, max_length=24)


class AskQuestionRequest(BaseModel):
    session_id: str = Field(..., min_length=24, max_length=24)
    question: str = Field(..., min_length=1, max_length=8000)


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    message_type: Optional[str] = None
    created_at: datetime
    metadata_json: Optional[str] = None


class SessionBoardTurnOut(BaseModel):
    turn_index: int
    content: str = ""
    instruction_timeline_v3: dict[str, Any] | None = None
    timeline_metadata: dict[str, Any] | None = None
    planner_source: str | None = None
    visual: dict[str, Any] | None = None
    zone: int | None = None
    cluster_index: int | None = None
    concept_index: int | None = None
    concept_id: str | None = None
    created_at: datetime


class LearningPathSessionOut(BaseModel):
    session_plan_id: str
    sequence_number: int
    title: str
    state: Literal["completed", "active", "available", "locked"]


class PlanProgressionOut(BaseModel):
    learning_path: list[LearningPathSessionOut] = Field(default_factory=list)
    last_transition: dict[str, Any] | None = None
    completion_percentage: float = 0.0
    status: str = "not_started"
    resume_pointer: dict[str, Any] | None = None
    transition: dict[str, Any] | None = None


class SessionRestoreResponse(BaseModel):
    session_id: str
    topic_id: str
    flow_state: str
    current_concept: str | None = None
    current_concept_index: int | None = None
    total_concepts: int | None = None
    current_zone: int | None = None
    meta: dict[str, Any] | None = None
    messages: list[ChatMessageOut]
    board_turns: list[SessionBoardTurnOut]
    pending_board: SessionBoardTurnOut | None = None
    restore_static_beat_index: int | None = None
    student_scratchpad_notes: str | None = None
    progression: PlanProgressionOut | None = None


class BoardCheckpointRequest(BaseModel):
    beat_index: int = Field(..., ge=0, le=500)
    timeline_id: str | None = Field(default=None, max_length=200)


class ScratchpadNotesRequest(BaseModel):
    content: str = Field(default="", max_length=50_000)


class RecommendedTopicOut(BaseModel):
    """One next-topic suggestion returned after session completion."""

    id: str
    name: str
    reason: str
    score: float


class AskQuestionResponse(BaseModel):
    answer: str
    orchestrator: dict | None = None
    type: str | None = None
    question: str | None = None
    root_topic_id: str | None = None
    difficulty: str | None = None
    correct: bool | None = None
    suggestion: str | None = None
    suggested_difficulty: str | None = None
    # Quiz: bank / AI metadata (when type == "quiz")
    expected_answer: str | None = None
    source: str | None = None
    concept: str | None = None
    questions: list[dict[str, Any]] | None = None
    cluster_index: int | None = None
    # Teacher flow: structured UI hints
    message: str | None = None
    current_concept: str | None = None
    buttons: list[dict[str, str]] | None = None
    visual: dict[str, Any] | None = None
    pedagogy_card: dict[str, Any] | None = None
    # Zone 0 dual-channel (non-question prose): TTS uses message; ink may use display_text.
    writing_mode: str | None = None
    display_text: str | None = None
    # Timeline V3 board payload (authored VTSE → ITV3)
    instruction_timeline_v3: dict[str, Any] | None = None
    timeline_metadata: dict[str, Any] | None = None
    planner_source: str | None = None
    session_completion: Optional[EndSessionResponse] = None
    recommended_topics: list[RecommendedTopicOut] | None = None
    progression: PlanProgressionOut | None = None
    meta: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional teacher-progression UI hints (zone, cluster, concept indices, "
            "micro_quiz_hold 0|1)."
        ),
    )
    # Explicit ack fields (VT advance / VTSE opening / flow checkpoint continue).
    outcome: str | None = None
    flow_checkpoint_pending: int | None = None
    scene_index: int | None = None
    beat_index: int | None = None
    sentence_index: int | None = None
    accepted: bool | None = None
    status: str | None = None
    flow_state: str | None = None
    concept_index: int | None = None


class GenerateQuizRequest(BaseModel):
    session_id: str = Field(..., min_length=24, max_length=24)


class EvaluateAnswerRequest(BaseModel):
    session_id: str = Field(..., min_length=24, max_length=24)
    question: str = Field(..., min_length=1, max_length=8000)
    student_answer: str = Field(..., min_length=1, max_length=8000)


class EvaluateAssignmentRequest(BaseModel):
    assignment_id: str = Field(..., min_length=24, max_length=24)
    answers: list[Any] = Field(default_factory=list)


class StartSessionResponse(BaseModel):
    id: str


class SessionSummaryPayload(BaseModel):
    summary_text: str
    key_points_learned: list[str]
    mistakes_identified: list[str]
    strengths_identified: list[str]


class AssignmentBriefPayload(BaseModel):
    id: str
    difficulty_level: str
    status: str
    question_count: int
    focus_concepts: list[str]


class AssignmentQuestionStudentView(BaseModel):
    """One question as shown to the student (correct_answer never included when pending)."""

    source: Optional[str] = None
    question_id: Optional[str] = None
    question_text: str
    difficulty_level: Optional[Any] = None
    evaluation: Optional[dict[str, Any]] = None


class AssignmentDetailPayload(BaseModel):
    id: str
    topic_id: Optional[str] = None
    topic_name: Optional[str] = None
    session_id: Optional[str] = None
    status: str
    difficulty_level: str
    score: Optional[float] = None
    focus_concepts: list[str] = Field(default_factory=list)
    questions: list[AssignmentQuestionStudentView] = Field(default_factory=list)


class DetailedNotesResponse(BaseModel):
    topic_id: Optional[str] = None
    content_markdown: Optional[str] = None


class DetailedNoteBriefPayload(BaseModel):
    """Latest AI detailed note for the session topic (for deep links after end session)."""

    id: str
    topic_id: Optional[str] = None


class DetailedNoteListItemOut(BaseModel):
    id: str
    topic_id: str
    topic_name: Optional[str] = None


class DetailedNoteDetailOut(BaseModel):
    id: str
    topic_id: str
    topic_name: Optional[str] = None
    content_markdown: str


class EndSessionResponse(BaseModel):
    """Returned after session end: drives UI summary, notes notice, and optional practice assignment."""

    status: str = "ok"
    session_id: str
    summary: Optional[SessionSummaryPayload] = None
    assignment: Optional[AssignmentBriefPayload] = None
    detailed_notes_message: Optional[str] = None
    detailed_note: Optional[DetailedNoteBriefPayload] = None
    recommended_topics: list[RecommendedTopicOut] | None = None


async def build_end_session_response_payload(
    session_repository: SessionRepository,
    session_id: PydanticObjectId,
    current_user: User,
    recommended_topics: Optional[list[dict[str, Any]]] = None,
) -> EndSessionResponse:
    """Build the same client payload as the legacy /sessions/end response (after DB session is completed)."""
    rec_models: Optional[list[RecommendedTopicOut]] = None
    if recommended_topics is not None:
        rec_models = [RecommendedTopicOut(**d) for d in recommended_topics]

    existing = await session_repository.get_by_id(session_id)
    if existing is None:
        return EndSessionResponse(
            status="ok",
            session_id=str(session_id),
            summary=None,
            assignment=None,
            detailed_notes_message=None,
            detailed_note=None,
            recommended_topics=rec_models,
        )

    summary_payload: Optional[SessionSummaryPayload] = None
    summaries = (
        await SessionSummary.find(
            {
                "session_id": session_id,
                "student_id": current_user.id,
                "organization_id": current_user.organization_id,
            }
        )
        .sort([("_id", -1)])
        .limit(1)
        .to_list()
    )
    if summaries:
        s = summaries[0]
        summary_payload = SessionSummaryPayload(
            summary_text=s.summary_text,
            key_points_learned=list(s.key_points_learned or []),
            mistakes_identified=list(s.mistakes_identified or []),
            strengths_identified=list(s.strengths_identified or []),
        )

    assignment_payload: Optional[AssignmentBriefPayload] = None
    assignments = (
        await SessionAssignment.find(
            {
                "session_id": session_id,
                "student_id": current_user.id,
            }
        )
        .sort([("_id", -1)])
        .limit(1)
        .to_list()
    )
    if assignments:
        a = assignments[0]
        qs = a.questions if isinstance(a.questions, list) else []
        assignment_payload = AssignmentBriefPayload(
            id=str(a.id),
            difficulty_level=str(a.difficulty_level),
            status=str(a.status),
            question_count=len(qs),
            focus_concepts=list(a.focus_concepts or []),
        )

    latest_topic_notes = (
        await TopicNote.find(
            {
                "topic_id": existing.topic_id,
                "organization_id": current_user.organization_id,
                "note_type": "detailed",
                "source_type": "ai",
                "approved": True,
            }
        )
        .sort([("_id", -1)])
        .limit(1)
        .to_list()
    )
    detailed_note_payload: Optional[DetailedNoteBriefPayload] = None
    if latest_topic_notes:
        ln = latest_topic_notes[0]
        detailed_note_payload = DetailedNoteBriefPayload(
            id=str(ln.id),
            topic_id=str(existing.topic_id) if existing.topic_id else None,
        )

    return EndSessionResponse(
        status="ok",
        session_id=str(session_id),
        summary=summary_payload,
        assignment=assignment_payload,
        detailed_notes_message=None,
        detailed_note=detailed_note_payload,
        recommended_topics=rec_models,
    )


@router.post("/start")
async def start_session(
    body: StartSessionRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> StartSessionResponse | dict[str, Any]:
    """Start or resume flow for a topic (one in-progress session per student per topic)."""
    from beanie.odm.fields import PydanticObjectId

    try:
        topic_id = PydanticObjectId(body.topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")

    service = SessionService(session_repository, topic_repository)
    topic_doc = await TeacherTopic.get(topic_id)
    if topic_doc is None:
        topic_doc = await Topic.get(topic_id)
    if topic_doc is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    runtime_manifest: Optional[RuntimeCurriculumManifest] = None
    if body.catalog_session_plan_id:
        try:
            plan_oid = PydanticObjectId(body.catalog_session_plan_id.strip())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid catalog_session_plan_id")
        plan = await ClassSessionPlanService().get_published_catalog_plan(
            plan_oid,
            catalog_topic_id=topic_id,
        )
        from app.services.runtime.curriculum_resolution_service import (
            CurriculumResolutionService,
        )

        try:
            runtime_manifest = CurriculumResolutionService().resolve_catalog_session_plan(
                plan
            )
        except CurriculumResolutionError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
    else:
        runtime_manifest = await _runtime_manifest_for_topic_start(topic_doc)
    try:
        out = await service.start_session(
            current_user.id,
            topic_id,
            action=body.action,
            curriculum_class_id=body.curriculum_class_id,
            curriculum_subject_id=body.curriculum_subject_id,
            student_organization_id=current_user.organization_id,
            runtime_curriculum_manifest=runtime_manifest,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(out, dict):
        return out
    return StartSessionResponse(id=str(out.id))


@router.get("/active")
async def get_active_session(
    topic_id: str = Query(
        ...,
        min_length=24,
        max_length=24,
        description="Topic to scope the active (in-progress) session",
    ),
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
):
    """Return the in-progress session for this user and topic, or 404 if none."""
    from beanie.odm.fields import PydanticObjectId

    try:
        tid = PydanticObjectId(topic_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid topic_id")

    service = SessionService(session_repository, topic_repository)
    session = await service.get_active_session_for_topic(
        current_user.id,
        tid,
        student_organization_id=current_user.organization_id,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session for this topic",
        )
    topic = await topic_repository.get_by_id(session.topic_id)
    if topic is None:
        topic = await TeacherTopic.get(session.topic_id)
    try:
        payload = dict(session.model_dump())
    except Exception:
        payload = dict(session)
    _meta = build_teacher_session_meta(session, topic)
    if _meta is not None:
        payload["meta"] = _meta
    return payload


@router.post("/ask", response_model=AskQuestionResponse)
async def ask_tutor_question(
    body: AskQuestionRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    event_repository: EventRepository = Depends(get_event_repository),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
    recommendation_repository: RecommendationRepository = Depends(
        get_recommendation_repository
    ),
    knowledge_gap_repository: KnowledgeGapRepository = Depends(
        get_knowledge_gap_repository
    ),
    topic_progression_repository: TopicProgressionRepository = Depends(
        get_topic_progression_repository
    ),
) -> AskQuestionResponse:
    """Answer a question using RAG for the active session topic (or a detected topic from the question)."""
    from beanie.odm.fields import PydanticObjectId

    try:
        session_id = PydanticObjectId(body.session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    mastery_service = MasteryService(
        session_repository, event_repository, mastery_repository
    )
    recommendation_service = RecommendationService(
        topic_repository,
        mastery_repository,
        recommendation_repository,
        knowledge_gap_repository,
        topic_progression_repository,
    )
    service = SessionService(
        session_repository,
        topic_repository,
        mastery_service=mastery_service,
        recommendation_service=recommendation_service,
    )
    try:
        result = await service.answer_tutor_question(
            session_id=session_id,
            student_id=current_user.id,
            question=question,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(result, dict):
        want_completion = bool(result.pop("_include_completion_payload", False))
        recommended_topics_raw = result.pop("_recommended_topics", None)
        progression_raw = result.pop("progression", None)
        meta_for_response: dict[str, Any] | None = None
        try:
            sess_reload = await session_repository.get_by_id(session_id)
            if sess_reload is not None:
                top = await topic_repository.get_by_id(sess_reload.topic_id)
                if top is None:
                    top = await TeacherTopic.get(sess_reload.topic_id)
                meta_for_response = build_teacher_session_meta(sess_reload, top)
                if isinstance(result, dict) and result.get("cluster_teachback_board"):
                    meta_for_response = {
                        **(meta_for_response or {}),
                        "cluster_teachback_board": True,
                    }
                if isinstance(result, dict) and result.get("cluster_teachback_panel"):
                    meta_for_response = {
                        **(meta_for_response or {}),
                        "cluster_teachback_panel": True,
                    }
                if isinstance(result, dict) and result.get(
                    "concept_teaching_await_vtse_done"
                ) in (1, True, "1"):
                    meta_for_response = {
                        **(meta_for_response or {}),
                        "concept_teaching_await_vtse_done": 1,
                        "micro_quiz_hold": 0,
                    }
        except Exception:
            meta_for_response = None
        completion_payload: Optional[EndSessionResponse] = None
        if want_completion:
            rec_for_payload: Optional[list[dict[str, Any]]] = None
            if isinstance(recommended_topics_raw, list):
                rec_for_payload = recommended_topics_raw
            completion_payload = await build_end_session_response_payload(
                session_repository,
                session_id,
                current_user,
                recommended_topics=rec_for_payload,
            )
        response_text = str(result.get("answer", "")).strip()
        if not response_text:
            msg = str(result.get("message", "")).strip()
            q = str(result.get("question", "")).strip()
            response_text = f"{msg}\n\n{q}".strip() if q else msg
        return AskQuestionResponse(
            answer=response_text,
            orchestrator=result.get("orchestrator"),
            type=(str(result.get("type")) if result.get("type") is not None else None),
            question=(
                str(result.get("question"))
                if result.get("question") is not None
                else None
            ),
            root_topic_id=(
                str(result.get("topic_id"))
                if result.get("type") == "root_cause"
                and result.get("topic_id") is not None
                else None
            ),
            difficulty=(
                str(result.get("difficulty"))
                if result.get("difficulty") is not None
                else None
            ),
            correct=(
                bool(result.get("correct"))
                if result.get("correct") is not None
                else None
            ),
            suggestion=(
                str(result.get("suggestion"))
                if result.get("suggestion") is not None
                else None
            ),
            suggested_difficulty=(
                str(result.get("suggested_difficulty"))
                if result.get("suggested_difficulty") is not None
                else None
            ),
            expected_answer=(
                str(result.get("answer"))
                if result.get("type") == "quiz" and result.get("answer") is not None
                else None
            ),
            source=(
                str(result.get("source"))
                if result.get("type") == "quiz" and result.get("source") is not None
                else None
            ),
            concept=(
                str(result.get("concept"))
                if result.get("type") == "quiz"
                and result.get("concept") is not None
                and str(result.get("concept")).strip() != ""
                else None
            ),
            message=(
                coerce_plain_text_reply(str(result.get("message")))
                if result.get("message") is not None
                else None
            ),
            current_concept=(
                str(result.get("current_concept"))
                if result.get("current_concept") is not None
                and str(result.get("current_concept")).strip() != ""
                else None
            ),
            buttons=result.get("buttons") if isinstance(result.get("buttons"), list) else None,
            visual=(
                result.get("visual") if isinstance(result.get("visual"), dict) else None
            ),
            pedagogy_card=(
                result.get("pedagogy_card")
                if isinstance(result.get("pedagogy_card"), dict)
                else None
            ),
            writing_mode=(
                str(result.get("writing_mode")).strip()
                if result.get("writing_mode") is not None
                and str(result.get("writing_mode")).strip() != ""
                else None
            ),
            display_text=(
                str(result.get("display_text"))
                if result.get("display_text") is not None
                else None
            ),
            instruction_timeline_v3=(
                result.get("instruction_timeline_v3")
                if isinstance(result.get("instruction_timeline_v3"), dict)
                else None
            ),
            timeline_metadata=(
                result.get("timeline_metadata")
                if isinstance(result.get("timeline_metadata"), dict)
                else None
            ),
            planner_source=(
                str(result.get("planner_source"))
                if result.get("planner_source") is not None
                else None
            ),
            session_completion=completion_payload,
            recommended_topics=(
                completion_payload.recommended_topics if completion_payload else None
            ),
            progression=_plan_progression_out(
                progression_raw if isinstance(progression_raw, dict) else None
            ),
            meta=meta_for_response,
            outcome=(
                str(result.get("outcome")).strip()
                if result.get("outcome") is not None
                and str(result.get("outcome")).strip() != ""
                else None
            ),
            flow_checkpoint_pending=(
                int(result.get("flow_checkpoint_pending"))
                if result.get("flow_checkpoint_pending") is not None
                and str(result.get("flow_checkpoint_pending")).strip() != ""
                else None
            ),
            scene_index=(
                int(result.get("scene_index"))
                if result.get("scene_index") is not None
                and str(result.get("scene_index")).strip() != ""
                else None
            ),
            beat_index=(
                int(result.get("beat_index"))
                if result.get("beat_index") is not None
                and str(result.get("beat_index")).strip() != ""
                else None
            ),
            sentence_index=(
                int(result.get("sentence_index"))
                if result.get("sentence_index") is not None
                and str(result.get("sentence_index")).strip() != ""
                else None
            ),
            accepted=(
                bool(result.get("accepted"))
                if result.get("accepted") is not None
                else None
            ),
            status=(
                str(result.get("status")).strip()
                if result.get("status") is not None
                and str(result.get("status")).strip() != ""
                else None
            ),
            flow_state=(
                str(result.get("flow_state")).strip()
                if result.get("flow_state") is not None
                and str(result.get("flow_state")).strip() != ""
                else None
            ),
            concept_index=(
                int(result.get("concept_index"))
                if result.get("concept_index") is not None
                and str(result.get("concept_index")).strip() != ""
                else None
            ),
        )
    return AskQuestionResponse(answer=result)


@router.post("/generate-quiz")
async def generate_quiz(
    body: GenerateQuizRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
):
    """Expose generate_quiz_question for test UI and clients."""
    from beanie.odm.fields import PydanticObjectId

    try:
        session_id = PydanticObjectId(body.session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = SessionService(session_repository, topic_repository)
    try:
        return await service.generate_quiz_question(
            session_id=session_id,
            student_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/evaluate-answer")
async def evaluate_answer(
    body: EvaluateAnswerRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    event_repository: EventRepository = Depends(get_event_repository),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
):
    """Expose evaluate_student_answer (requires MasteryService)."""
    from beanie.odm.fields import PydanticObjectId

    try:
        session_id = PydanticObjectId(body.session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    mastery_service = MasteryService(
        session_repository, event_repository, mastery_repository
    )
    service = SessionService(
        session_repository,
        topic_repository,
        mastery_service=mastery_service,
    )
    try:
        return await service.evaluate_student_answer(
            session_id=session_id,
            student_id=current_user.id,
            question=body.question.strip(),
            student_answer=body.student_answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/assignments")
async def list_assignments(
    current_user: User = Depends(get_current_user),
):
    assignments = await SessionAssignment.find(
        {
            "organization_id": current_user.organization_id,
            "student_id": current_user.id,
        }
    ).sort([("_id", -1)]).limit(50).to_list()
    return assignments


def _assignment_to_student_detail(
    assignment: SessionAssignment,
    topic_name: Optional[str] = None,
) -> AssignmentDetailPayload:
    qs_out: list[AssignmentQuestionStudentView] = []
    raw_questions = (
        assignment.questions if isinstance(assignment.questions, list) else []
    )
    is_done = assignment.status == "completed"
    for q in raw_questions:
        if not isinstance(q, dict):
            continue
        qid = q.get("question_id")
        ev = q.get("evaluation") if is_done else None
        ev_dict: dict[str, Any] | None = None
        if isinstance(ev, dict):
            ev_dict = cast(dict[str, Any], ev)
        qs_out.append(
            AssignmentQuestionStudentView(
                source=str(q.get("source")) if q.get("source") else None,
                question_id=str(qid) if qid is not None else None,
                question_text=str(q.get("question_text", "")).strip(),
                difficulty_level=q.get("difficulty_level"),
                evaluation=ev_dict,
            )
        )
    sid = getattr(assignment, "session_id", None)
    return AssignmentDetailPayload(
        id=str(assignment.id),
        topic_id=str(assignment.topic_id) if assignment.topic_id else None,
        topic_name=topic_name,
        session_id=str(sid) if sid is not None else None,
        status=str(assignment.status),
        difficulty_level=str(assignment.difficulty_level),
        score=(
            float(assignment.score)
            if assignment.score is not None
            else None
        ),
        focus_concepts=list(assignment.focus_concepts or []),
        questions=qs_out,
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=AssignmentDetailPayload,
)
async def get_assignment_detail(
    assignment_id: str,
    current_user: User = Depends(get_current_user),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> AssignmentDetailPayload:
    """Return one assignment for the current student (no correct answers while pending)."""
    try:
        aid = PydanticObjectId(assignment_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid assignment_id")
    assignment = await SessionAssignment.get(aid)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    if (
        assignment.student_id != current_user.id
        or assignment.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to view this assignment",
        )
    topic_nm: Optional[str] = None
    if assignment.topic_id is not None:
        t = await topic_repository.get_by_id(assignment.topic_id)
        if t is not None:
            topic_nm = t.topic_name
    return _assignment_to_student_detail(assignment, topic_name=topic_nm)


async def _topic_name_for_id(
    topic_repository: TopicRepository, topic_id: Optional[Any]
) -> Optional[str]:
    if topic_id is None:
        return None
    t = await topic_repository.get_by_id(topic_id)
    return t.topic_name if t is not None else None


@router.get("/detailed-notes", response_model=list[DetailedNoteListItemOut])
async def list_detailed_notes(
    current_user: User = Depends(get_current_user),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> list[DetailedNoteListItemOut]:
    """AI-approved detailed topic notes for the student's organization (same scope as curriculum)."""
    notes = (
        await TopicNote.find(
            {
                "organization_id": current_user.organization_id,
                "note_type": "detailed",
                "source_type": "ai",
                "approved": True,
            }
        )
        .sort([("_id", -1)])
        .limit(50)
        .to_list()
    )
    topic_ids = list(
        {n.topic_id for n in notes if getattr(n, "topic_id", None) is not None}
    )
    name_by_tid: dict[str, str] = {}
    if topic_ids:
        topics = await Topic.find(In(Topic.id, topic_ids)).to_list()
        for t in topics:
            name_by_tid[str(t.id)] = t.topic_name
    out: list[DetailedNoteListItemOut] = []
    for n in notes:
        tid = getattr(n, "topic_id", None)
        topic_id_str = str(tid) if tid is not None else ""
        nm = name_by_tid.get(topic_id_str) if topic_id_str else None
        out.append(
            DetailedNoteListItemOut(
                id=str(n.id),
                topic_id=topic_id_str,
                topic_name=nm,
            )
        )
    return out


@router.get(
    "/detailed-notes/{note_id}",
    response_model=DetailedNoteDetailOut,
)
async def get_detailed_note_detail(
    note_id: str,
    current_user: User = Depends(get_current_user),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> DetailedNoteDetailOut:
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
            detail="Not allowed to view this note",
        )
    if (
        note.note_type != "detailed"
        or note.source_type != "ai"
        or not note.approved
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to view this note",
        )
    tid = getattr(note, "topic_id", None)
    topic_nm = await _topic_name_for_id(topic_repository, tid)
    return DetailedNoteDetailOut(
        id=str(note.id),
        topic_id=str(tid) if tid is not None else "",
        topic_name=topic_nm,
        content_markdown=str(note.content_markdown or ""),
    )


@router.post("/assignments/evaluate")
async def evaluate_assignment(
    body: EvaluateAssignmentRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
    event_repository: EventRepository = Depends(get_event_repository),
    mastery_repository: MasteryRepository = Depends(get_mastery_repository),
):
    mastery_service = MasteryService(
        session_repository, event_repository, mastery_repository
    )
    service = SessionService(
        session_repository,
        topic_repository,
        mastery_service=mastery_service,
    )
    try:
        return await service.evaluate_assignment(
            assignment_id=body.assignment_id,
            student_id=str(current_user.id),
            answers=body.answers,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{session_id}/messages",
    response_model=list[ChatMessageOut],
)
async def list_session_chat_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> list[ChatMessageOut]:
    """Persisted chat turns for the session (UI replay; tutor flow still from session state)."""
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = SessionService(session_repository, topic_repository)
    try:
        rows = await service.get_chat_messages(
            sid,
            current_user.id,
            limit=limit,
        )
    except ValueError as e:
        msg = str(e).lower()
        detail = str(e)
        if "not found" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail,
            )
        if "does not belong" in msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )
        raise HTTPException(status_code=400, detail=detail)

    out: list[ChatMessageOut] = []
    for r in rows:
        role = r.get("role")
        if role not in ("user", "assistant"):
            continue
        created = r.get("created_at")
        if created is None:
            continue
        out.append(
            ChatMessageOut(
                role=cast(Literal["user", "assistant"], role),
                content=str(r.get("content") or ""),
                message_type=(
                    str(r["message_type"])
                    if r.get("message_type") is not None
                    else None
                ),
                created_at=created,
                metadata_json=(
                    str(r["metadata_json"])
                    if r.get("metadata_json") is not None
                    else None
                ),
            )
        )
    return out


@router.get(
    "/{session_id}/restore",
    response_model=SessionRestoreResponse,
)
async def restore_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
) -> SessionRestoreResponse:
    """Resume snapshot: chat history, persisted board turns, session meta — no re-generation."""
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = SessionService(session_repository, topic_repository)
    try:
        payload = await service.get_session_restore_payload(
            sid,
            current_user.id,
        )
    except ValueError as e:
        msg = str(e).lower()
        detail = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        if "does not belong" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    messages_out: list[ChatMessageOut] = []
    for r in payload.get("messages") or []:
        role = r.get("role")
        if role not in ("user", "assistant"):
            continue
        created = r.get("created_at")
        if created is None:
            continue
        messages_out.append(
            ChatMessageOut(
                role=cast(Literal["user", "assistant"], role),
                content=str(r.get("content") or ""),
                message_type=(
                    str(r["message_type"]) if r.get("message_type") is not None else None
                ),
                created_at=created,
                metadata_json=(
                    str(r["metadata_json"])
                    if r.get("metadata_json") is not None
                    else None
                ),
            )
        )

    def _board_turn_out(raw: dict[str, Any]) -> SessionBoardTurnOut:
        created = raw.get("created_at")
        if created is None:
            from datetime import datetime as _dt

            created = _dt.utcnow()
        return SessionBoardTurnOut(
            turn_index=int(raw.get("turn_index") or 0),
            content=str(raw.get("content") or ""),
            instruction_timeline_v3=(
                raw.get("instruction_timeline_v3")
                if isinstance(raw.get("instruction_timeline_v3"), dict)
                else None
            ),
            timeline_metadata=(
                raw.get("timeline_metadata")
                if isinstance(raw.get("timeline_metadata"), dict)
                else None
            ),
            planner_source=(
                str(raw["planner_source"]).strip()
                if raw.get("planner_source") is not None
                else None
            ),
            visual=raw.get("visual") if isinstance(raw.get("visual"), dict) else None,
            zone=raw.get("zone") if isinstance(raw.get("zone"), int) else None,
            cluster_index=(
                raw.get("cluster_index")
                if isinstance(raw.get("cluster_index"), int)
                else None
            ),
            concept_index=(
                raw.get("concept_index")
                if isinstance(raw.get("concept_index"), int)
                else None
            ),
            concept_id=(
                str(raw["concept_id"]).strip()
                if raw.get("concept_id") is not None
                else None
            ),
            created_at=created,
        )

    board_turns_raw = payload.get("board_turns") or []
    board_turns_out = [
        _board_turn_out(t) for t in board_turns_raw if isinstance(t, dict)
    ]
    pending_raw = payload.get("pending_board")
    pending_out = (
        _board_turn_out(pending_raw) if isinstance(pending_raw, dict) else None
    )

    return SessionRestoreResponse(
        session_id=str(payload.get("session_id") or session_id),
        topic_id=str(payload.get("topic_id") or ""),
        flow_state=str(payload.get("flow_state") or "idle"),
        current_concept=(
            str(payload["current_concept"]).strip()
            if payload.get("current_concept") is not None
            else None
        ),
        current_concept_index=(
            int(payload["current_concept_index"])
            if isinstance(payload.get("current_concept_index"), int)
            else None
        ),
        total_concepts=(
            int(payload["total_concepts"])
            if isinstance(payload.get("total_concepts"), int)
            else None
        ),
        current_zone=(
            int(payload["current_zone"])
            if isinstance(payload.get("current_zone"), int)
            else None
        ),
        meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else None,
        messages=messages_out,
        board_turns=board_turns_out,
        pending_board=pending_out,
        restore_static_beat_index=(
            int(payload["restore_static_beat_index"])
            if isinstance(payload.get("restore_static_beat_index"), int)
            else None
        ),
        student_scratchpad_notes=(
            str(payload["student_scratchpad_notes"])
            if payload.get("student_scratchpad_notes")
            else None
        ),
        progression=_plan_progression_out(
            payload.get("progression")
            if isinstance(payload.get("progression"), dict)
            else None
        ),
    )


@router.post("/{session_id}/board-checkpoint")
async def save_board_checkpoint(
    session_id: str,
    body: BoardCheckpointRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
):
    """Persist VTSE playback beat index for partial board restore on reload."""
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = SessionService(session_repository, topic_repository)
    try:
        await service.save_board_playback_checkpoint(
            sid,
            current_user.id,
            body.beat_index,
            timeline_id=body.timeline_id,
        )
    except ValueError as e:
        msg = str(e).lower()
        detail = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        if "does not belong" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "beat_index": body.beat_index}


@router.put("/{session_id}/scratchpad")
async def save_session_scratchpad(
    session_id: str,
    body: ScratchpadNotesRequest,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
    topic_repository: TopicRepository = Depends(get_topic_repository),
):
    """Persist student scratchpad notes for this learning session."""
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    service = SessionService(session_repository, topic_repository)
    try:
        await service.save_student_scratchpad_notes(
            sid, current_user.id, body.content
        )
    except ValueError as e:
        msg = str(e).lower()
        detail = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        if "does not belong" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True}


@router.get(
    "/{session_id}/detailed-notes",
    response_model=DetailedNotesResponse,
)
async def get_detailed_notes(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_repository: SessionRepository = Depends(get_session_repository),
):
    """
    Return reusable detailed topic notes (student view).
    Notes are selected based on student's saved preferences (teaching_style,
    interest_category, difficulty_level), with a fallback to any approved
    detailed note for the topic.
    """
    try:
        sid = PydanticObjectId(session_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session = await session_repository.get_by_id(sid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    if session.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to view notes for this session",
        )

    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    teaching_style = (
        student_profile.preferred_teaching_style
        if student_profile is not None
        else None
    )
    interests = student_profile.interests if student_profile is not None else []
    interest_category = interests[0] if interests else "general"
    difficulty_level = (
        student_profile.preferred_depth if student_profile is not None else None
    )

    # Prefer the note matching the student's preference settings.
    preferred = await TopicNote.find_one(
        {
            "topic_id": session.topic_id,
            "organization_id": session.organization_id,
            "note_type": "detailed",
            "teaching_style": teaching_style,
            "interest_category": interest_category,
            "difficulty_level": difficulty_level,
            "source_type": "ai",
            "approved": True,
        }
    )

    note = preferred
    if note is None:
        # Fallback: any approved detailed note for this topic/org.
        notes = await TopicNote.find(
            {
                "topic_id": session.topic_id,
                "organization_id": session.organization_id,
                "note_type": "detailed",
                "source_type": "ai",
                "approved": True,
            }
        ).sort([("_id", -1)]).limit(1).to_list()
        note = notes[0] if notes else None

    return DetailedNotesResponse(
        topic_id=str(session.topic_id) if getattr(session, "topic_id", None) else None,
        content_markdown=(note.content_markdown if note is not None else None),
    )


@router.post("/end", include_in_schema=False)
async def end_session_removed() -> None:
    """Deprecated: sessions are finalized when the student completes the topic, not via manual end."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Manual session end is no longer supported. You can leave the lesson "
            "without calling this API. Summaries and assignments are created when "
            "you complete the topic."
        ),
    )

