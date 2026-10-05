import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from typing import Any, List, Literal, Optional, cast

import httpx
from beanie.odm.fields import PydanticObjectId

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.models.content.topic_notes import TopicNote
from app.models.identification.student_profiles import StudentProfile
from app.models.intelligence.ai_generation_logs import AIGenerationLog
from app.models.learning.mastery_records import (
    MasteryRecord,
    mastery_record_filter,
    normalize_concept,
)
from app.models.learning.session_assignments import SessionAssignment
from app.models.learning.teachback_evaluations import TeachbackEvaluation
from app.models.learning.session_events import SessionEvent
from app.models.summaries.session_summaries import SessionSummary
from app.enums.learning_enums import SessionEventType
from app.repositories.event_repository import EventRepository
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.models.curriculum.prerequisite_graph import PrerequisiteGraph
from app.models.curriculum.topics import Topic
from app.models.learning.sessions import Session
from app.models.organization import Organization
from app.models.runtime.runtime_curriculum_manifest import RuntimeCurriculumManifest
from app.models.teacher_topic import TeacherTopic
from app.repositories.board_turn_repository import BoardTurnRepository
from app.repositories.message_repository import MessageRepository
from app.services.handlers.session_meta import build_teacher_session_meta
from app.repositories.session_repository import SessionRepository
from app.repositories.topic_repository import TopicRepository
from app.services.embedding_service import (
    SIMILARITY_THRESHOLD,
    find_best_concept_with_score,
    get_embedding,
)
from app.services.mastery_service import MasteryService
from app.services.misconception_service import handle_misconception
from app.services.handlers.cluster_utils import (
    flat_index_is_last_in_its_cluster,
    resolve_clusters,
)
from app.services.handlers.context import HandlerContext
from app.services.handlers.explanation_handler import (
    build_explanation_response,
    build_feedback_response,
    generate_tutor_rag_reply as _explain_generate_rag_reply,
    should_run_micro_teaching,
    teacher_advance_skip as _explain_teacher_advance_skip,
    teacher_buttons,
    teacher_explain_turn as _explain_teacher_explain_turn,
    teacher_micro_teaching_opening,
    teacher_micro_teaching_process_reply,
)
from app.services.handlers.flow_checkpoint_handler import (
    handle_flow_checkpoint_continue,
    handle_flow_checkpoint_pause,
    handle_flow_checkpoint_question,
    maybe_dispatch_flow_checkpoint,
    parse_flow_checkpoint_continue_timeline,
    parse_flow_checkpoint_pause_request,
)
from app.services.handlers.concept_question_orchestrator import (
    handle_concept_notes_continue,
    handle_concept_questions_dispatch,
    is_concept_notes_mode,
    is_concept_questions_mode,
    normalize_concept_question_action,
)
from app.services.handlers.cluster_quiz_orchestrator import (
    handle_cluster_quiz_dispatch,
    is_cluster_quiz_mode,
    normalize_cluster_quiz_action,
)
from app.services.handlers.teachback_handler import (
    evaluate_student_answer as _teachback_evaluate_student_answer,
    handle_cluster_check_input as _teachback_handle_cluster_check_input,
    handle_teachback_input as _teachback_handle_input,
)
from app.core.constants import MICRO_TEACH_STEP_READY_QUIZ, RETRIEVAL_PASS_THRESHOLD
from app.services.evaluation_engine import evaluate_answer as _engine_evaluate
from app.services.handlers.quiz_handler import (
    build_quiz_response,
    extract_quiz_batch_count,
    generate_and_return_quiz as _quiz_generate_and_return,
    generate_and_return_cluster_quiz as _quiz_generate_cluster_and_return,
    generate_quiz_question as _quiz_generate_question,
    generate_zone3_hint as _quiz_generate_zone3_hint,
    quiz_reply_seeks_help,
)
from app.services.handlers.zone0_handler import (
    diagnostic_filtered_prereq_ids,
    zone0_after_curiosity_answer,
    zone0_complete_to_zone1,
    zone0_emit_anchor,
    zone0_emit_curiosity,
    zone0_emit_prereq_or_skip,
    zone0_handle_prereq_answer,
    zone0_idle_dispatch,
    zone0_skip,
    zone0_student_text_confirms_ready,
)
from app.services.orchestrator_service import OrchestratorService
from app.services.rag_service import RAGService, _rank_by_similarity
from app.services.recommendation_service import RecommendationService
from app.services.teacher_topic_service import normalize_topic_name

logger = logging.getLogger(__name__)


class SessionService:
    """Orchestrates starting, fetching, and ending learning sessions."""

    def __init__(
        self,
        session_repository: SessionRepository,
        topic_repository: TopicRepository,
        mastery_service: Optional[MasteryService] = None,
        recommendation_service: Optional[RecommendationService] = None,
        message_repository: Optional[MessageRepository] = None,
        board_turn_repository: Optional[BoardTurnRepository] = None,
    ) -> None:
        self.session_repository = session_repository
        self.topic_repository = topic_repository
        self.mastery_service = mastery_service
        self.recommendation_service = recommendation_service
        self._message_repository = message_repository or MessageRepository()
        self._board_turn_repository = board_turn_repository or BoardTurnRepository()

    def _build_handler_context(self) -> HandlerContext:
        """Build a HandlerContext from the current service's dependencies."""
        return HandlerContext(
            session_repository=self.session_repository,
            topic_repository=self.topic_repository,
            mastery_service=self.mastery_service,
        )

    async def _get_topic_or_teacher_topic(
        self, topic_id: PydanticObjectId
    ) -> Topic | TeacherTopic | None:
        t = await self.topic_repository.get_by_id(topic_id)
        if t is not None:
            return t
        return await TeacherTopic.get(topic_id)

    @staticmethod
    def _effective_session_organization_id(
        topic: Topic | TeacherTopic,
        student_organization_id: Optional[PydanticObjectId],
    ) -> Optional[PydanticObjectId]:
        """
        Session rows require a tenant org. Global curriculum topics use ``organization_id`` null;
        scope the session with the student's organization instead.
        """
        if isinstance(topic, TeacherTopic):
            return topic.organization_id
        if topic.organization_id is not None:
            return topic.organization_id
        return student_organization_id

    @staticmethod
    async def _curriculum_subject_oid_for_teacher_topic(
        tt: TeacherTopic,
    ) -> Optional[PydanticObjectId]:
        org = await Organization.get(tt.organization_id)
        if org is None:
            return None
        for c in org.classes or []:
            if c.id != tt.class_id:
                continue
            for s in c.subjects or []:
                if s.id == tt.subject_id:
                    return s.curriculum_subject_id
        return None


    @staticmethod
    def _is_teacher_progression(session: Session) -> bool:
        return (getattr(session, "total_concepts", 0) or 0) > 0

    @staticmethod
    def _session_concept_sequence(
        session: Session, topic: Topic | TeacherTopic | None
    ) -> list[str]:
        kc = list(getattr(session, "key_concepts", None) or [])
        if kc:
            flat = [str(c).strip() for c in kc if c is not None and str(c).strip()]
        elif topic is None:
            flat = []
        else:
            flat = [
                str(c).strip()
                for c in (topic.key_concepts or [])
                if c is not None and str(c).strip()
            ]

        # ── Phase 1 cluster injection point ──────────────────────────────────
        # resolve_clusters is the single entry point for deriving cluster
        # structure from a session snapshot.  The flat return value is
        # unchanged; Phase 2 will add cluster-aware routing on top of this.
        resolve_clusters(flat, getattr(session, "concept_clusters", None))

        return flat

    async def _resolve_key_concepts_for_topic(
        self,
        topic: Topic,
        *,
        curriculum_class_id: str | None = None,
        curriculum_subject_id: str | None = None,
    ) -> tuple[list[str], Optional[list[list[str]]]]:
        """
        Resolve the canonical key_concepts (and optional concept_clusters) for a
        Topic, honouring the teacher-topic override when available.

        Returns:
            (key_concepts, concept_clusters) — concept_clusters may be None when
            neither the teacher topic nor the admin topic defines explicit clusters.
        """
        from app.models.organization import Organization
        from app.models.teacher_topic import TeacherTopic

        cls_id = (curriculum_class_id or "").strip() or None
        sub_id = (curriculum_subject_id or "").strip() or None
        org_id = topic.organization_id

        use_teacher = False
        if org_id and cls_id and sub_id:
            org_row = await Organization.get(org_id)
            if org_row is not None and org_row.organization_type == "institution":
                use_teacher = True

        if use_teacher:
            topic_key = normalize_topic_name(topic.topic_name or "")
            if topic_key:
                candidates = await TeacherTopic.find(
                    TeacherTopic.organization_id == org_id,
                    TeacherTopic.class_id == cls_id,
                    TeacherTopic.subject_id == sub_id,
                ).to_list()
                tt = next(
                    (
                        row
                        for row in candidates
                        if normalize_topic_name(row.topic_name) == topic_key
                    ),
                    None,
                )
                if tt is not None:
                    teacher_kc = [
                        str(c).strip()
                        for c in (tt.key_concepts or [])
                        if c is not None and str(c).strip()
                    ]
                    if teacher_kc:
                        return teacher_kc, tt.concept_clusters

        admin_raw = topic.key_concepts or []
        admin = [
            str(c).strip()
            for c in admin_raw
            if c is not None and str(c).strip()
        ]
        kc = admin if admin else ["introduction"]
        return kc, topic.concept_clusters

    async def get_curriculum_for_session(
        self, session: Session, topic: Topic | TeacherTopic
    ) -> list[str]:
        if isinstance(topic, TeacherTopic):
            kc = [
                str(c).strip()
                for c in (topic.key_concepts or [])
                if c is not None and str(c).strip()
            ]
            return kc if kc else ["introduction"]
        # Unpack tuple — callers of this method only need key_concepts.
        kc, _ = await self._resolve_key_concepts_for_topic(
            topic,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        return kc

    def _get_current_concept(
        self, session: Session, topic: Topic | TeacherTopic | None
    ) -> str | None:
        concepts = self._session_concept_sequence(session, topic)
        if not concepts:
            return None
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        if idx < 0 or idx >= len(concepts):
            return None
        return concepts[idx]

    def _get_next_concept(
        self, session: Session, topic: Topic | TeacherTopic | None
    ) -> str | None:
        concepts = self._session_concept_sequence(session, topic)
        if not concepts:
            return None
        idx = int(getattr(session, "current_concept_index", 0) or 0) + 1
        if idx < 0 or idx >= len(concepts):
            return None
        return concepts[idx]

    def _rag_prompt_boundary_kwargs(
        self, session: Session, topic: Topic | TeacherTopic | None
    ) -> dict[str, Any]:
        if not self._is_teacher_progression(session):
            return {}
        concepts = self._session_concept_sequence(session, topic)
        if not concepts:
            return {}
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        if idx < 0:
            idx = 0
        if idx > len(concepts):
            idx = len(concepts)
        learned_list = concepts[:idx]
        next_concept = concepts[idx + 1] if idx + 1 < len(concepts) else None
        return {
            "enforce_knowledge_boundary": True,
            "learned_concepts_list": learned_list,
            "next_concept": next_concept,
        }

    @staticmethod
    def _teacher_flow_action(user_input: str) -> str | None:
        s = (user_input or "").strip().lower()
        if s.startswith("__action:"):
            return s.split(":", 1)[1].strip() or None
        s_clean = s.rstrip("!.?")
        if s_clean in ("start", "begin", "go", "yes", "ok", "okay", "sure"):
            return "start"
        if s_clean in ("skip", "skip concept", "skip this"):
            return "skip"
        if (
            "ask_another" in s
            or s_clean == "another question"
            or "another question" in s
        ):
            return "ask_another"
        if "explain_again" in s or "explain again" in s:
            return "explain_again"
        if (
            s_clean in ("ask_question", "ask question")
            or "have a question" in s
            or s == "i have a question"
        ):
            return "ask_question"
        if (
            s_clean in ("understand", "understood", "got it")
            or "i understand" in s
            or "makes sense" in s
        ):
            return "understand"
        return None

    @staticmethod
    def _looks_like_question_interrupt(user_input: str) -> bool:
        s = (user_input or "").strip().lower()
        if not s or s.startswith("__action:"):
            return False
        if "?" in s:
            return True
        starters = (
            "what ",
            "why ",
            "how ",
            "when ",
            "where ",
            "which ",
            "can ",
            "could ",
            "does ",
            "do ",
            "is ",
            "are ",
            "did ",
            "will ",
            "would ",
        )
        return any(s.startswith(st) for st in starters)

    @staticmethod
    def _is_no_more_questions_text(user_input: str) -> bool:
        s = (user_input or "").strip().lower().rstrip("!.?")
        if not s:
            return False
        no_markers = {
            "no",
            "nope",
            "none",
            "nothing",
            "thats all",
            "that's all",
            "no more",
            "no question",
            "no questions",
            "im good",
            "i'm good",
            "all good",
            "understood",
            "got it",
            "clear now",
            "lets continue",
            "let's continue",
            "continue",
        }
        return s in no_markers

    def _teacher_debug_flow(
        self, session: Session, topic: Topic | TeacherTopic | None
    ) -> None:
        next_c = self._get_next_concept(session, topic)
        print(
            "FLOW:",
            getattr(session, "flow_state", None),
            "CURRENT:",
            getattr(session, "current_concept", None),
            "NEXT:",
            next_c,
        )

    @staticmethod
    def _student_struggle_phrases() -> tuple[str, ...]:
        """Phrases indicating confusion or need for help (substring match on lowercased input)."""
        return (
            "don't understand",
            "dont understand",
            "do not understand",
            "still confused",
            "not clear",
            "isn't clear",
            "isnt clear",
            "unclear",
            "i don't know",
            "i dont know",
            "don't know",
            "dont know",
            "do not know",
            "idk",
            "i am confused",
            "i'm confused",
            "im confused",
            "iam confused",
            "very confused",
            "so confused",
            "confused about",
            "i am lost",
            "i'm lost",
            "im lost",
            "i'm stuck",
            "im stuck",
            "stuck on",
            "not sure",
            "unsure",
            "need help",
            "can you explain",
            "doesn't make sense",
            "doesnt make sense",
            "don't get it",
            "dont get it",
            "do not get it",
            "too hard",
            "too difficult",
            "no idea",
            "have no idea",
        )

    @staticmethod
    def _classify_intent(user_input: str, is_quiz_mode: bool) -> str:
        """
        Return a single intent label: EXPLAIN, QUIZ, ANSWER, CONFIRM, or UNKNOWN.
        Input must already be normalized (strip + lower) by the caller.
        """
        s = user_input.strip().lower()
        if is_quiz_mode:
            if any(p in s for p in SessionService._student_struggle_phrases()):
                return "EXPLAIN"
            t = s.strip().rstrip("!.?")
            if t in ("help", "explain", "hint", "hints"):
                return "EXPLAIN"
            if "what is" in s or "define" in s:
                return "EXPLAIN"
            return "ANSWER"
        s_clean = s.strip().rstrip("!.?")
        if s_clean in ("yes", "ok", "okay", "understood"):
            return "CONFIRM"
        if (
            "i understand" in s
            or "got it" in s
            or "makes sense" in s
        ):
            return "CONFIRM"
        if any(
            m in s
            for m in (
                "explain",
                "don't understand",
                "dont understand",
                "again",
                "what is",
                "define",
            )
        ):
            return "EXPLAIN"
        if any(m in s for m in ("quiz", "question", "test", "ask me")):
            return "QUIZ"
        if SessionService._looks_like_concept_explain_query(s):
            return "EXPLAIN"
        if SessionService._looks_like_short_factual_reply(s):
            return "ANSWER"
        return "UNKNOWN"

    @staticmethod
    def _is_concept_token(w: str) -> bool:
        if not w:
            return False
        if w.isdigit():
            return False
        return all(c.isalnum() or c == "-" for c in w)

    @staticmethod
    def _looks_like_concept_explain_query(s: str) -> bool:
        """Short vocabulary-style asks, e.g. 'numerator?' or 'improper fraction?'."""
        t = s.strip().lower()
        if not t or len(t) > 40:
            return False
        if any(h in t for h in ("quiz", "test", "ask me")):
            return False
        dismiss = (
            "yes",
            "no",
            "ok",
            "yeah",
            "yep",
            "nope",
            "nah",
            "sure",
            "bye",
            "thanks",
            "thank you",
        )
        if t in dismiss or t.rstrip("?") in dismiss:
            return False
        if t.endswith("?"):
            core = t[:-1].strip()
            words = core.split()
            if 1 <= len(words) <= 3 and len(core) <= 32:
                if all(SessionService._is_concept_token(w) for w in words):
                    return True
        words = t.split()
        if 1 <= len(words) <= 2 and len(t) <= 28:
            if all(SessionService._is_concept_token(w) for w in words):
                w0 = words[0]
                if w0 in ("yes", "no", "ok", "yeah", "yep", "nope", "nah", "sure"):
                    return False
                return True
        return False

    @staticmethod
    def _looks_like_short_factual_reply(s: str) -> bool:
        t = s.strip()
        if not t or len(t) > 48:
            return False
        low = t.lower()
        block = (
            "explain",
            "don't understand",
            "dont understand",
            "what is",
            "define",
            "quiz",
            "test",
            "ask me",
            "question",
        )
        if any(m in low for m in block):
            return False
        if any(c.isdigit() for c in t):
            return True
        if len(t.split()) <= 4 and len(t) <= 24:
            return True
        return False

    @staticmethod
    def _is_zone3_hint_request(user_input: str) -> bool:
        """
        Detect an explicit hint request in Zone 3 quiz mode.

        Triggers ONLY on clearly intentional, short phrases.  Long answers
        that happen to contain the word 'hint' (e.g. 'the hint here is that
        the formula uses velocity') are NOT detected because they exceed the
        word-count threshold.

        Rules:
          * Exact single-token match against known hint words, OR
          * Short phrase (≤ 8 words) that contains a recognised hint phrase.
        """
        s = user_input.strip().lower()
        words = s.split()

        # Exact single-word / two-word triggers (after stripping punctuation)
        _exact = {"hint", "hints", "clue", "clues", "tip", "tips", "stuck"}
        if s.rstrip("!.?") in _exact:
            return True

        # Short explicit phrases — only match when the total word count is small
        # so that real answers containing these words are not wrongly intercepted.
        if len(words) <= 8:
            _phrases = (
                "give me a hint",
                "need a hint",
                "can i get a hint",
                "give a hint",
                "a small hint",
                "just a hint",
                "any hint",
                "small clue",
                "give clue",
                "give me a clue",
                "need a clue",
                "i am stuck",
                "i'm stuck",
                "im stuck",
                "am stuck",
            )
            if any(ph in s for ph in _phrases):
                return True

        return False

    async def _detect_topic_from_query_simple(
        self,
        question: str,
        organization_id: PydanticObjectId,
    ) -> PydanticObjectId | None:
        """Same topic-routing idea as RAGService.detect_topic_from_query (topic name or key concept hit)."""
        question_lower = question.lower()
        topics = await self.topic_repository.get_many(
            filters={"organization_id": organization_id},
            limit=50,
        )
        for t in topics:
            if t.topic_name.lower() in question_lower:
                return t.id
            for concept in t.key_concepts or []:
                c = str(concept).lower().strip()
                if c and c in question_lower:
                    return t.id
        return None

    @staticmethod
    def _extract_matched_key_concept(
        question_lower: str,
        key_concepts: list[str],
    ) -> str | None:
        """Pick one key_concepts entry whose text appears in the question (longest match first)."""
        candidates = sorted(
            key_concepts,
            key=len,
            reverse=True,
        )
        for raw in candidates:
            c = str(raw).strip()
            if not c:
                continue
            if c.lower() in question_lower:
                return c
        return None

    async def _apply_session_concept_tracking(
        self,
        session: Session,
        question_raw: str,
        detected_topic_id: PydanticObjectId | None,
    ) -> None:
        """
        Set or hold session.current_concept from session curriculum (concept lock).
        Reset when the question clearly references another topic in this org.
        """
        topic = await self._get_topic_or_teacher_topic(session.topic_id)
        if topic is None:
            return
        qlow = question_raw.strip().lower()
        if not qlow:
            return

        if detected_topic_id is not None and detected_topic_id != session.topic_id:
            if getattr(session, "current_concept", None) is not None:
                session.current_concept = None
                await session.save()
            return

        concepts = self._session_concept_sequence(session, topic)
        if not concepts:
            if getattr(session, "current_concept", None) is not None:
                session.current_concept = None
                await session.save()
            return

        try:
            best_emb, score = await asyncio.to_thread(
                lambda: find_best_concept_with_score(
                    question_raw,
                    concepts,
                    topic_id=str(topic.id),
                )
            )
        except Exception as e:
            logger.warning("Semantic concept detection failed: %s", e)
            best_emb, score = None, 0.0

        if best_emb is not None and score > SIMILARITY_THRESHOLD:
            session.current_concept = str(best_emb).strip()[:500]
            await session.save()
            return

        matched = self._extract_matched_key_concept(qlow, concepts)
        cur_norm = normalize_concept(getattr(session, "current_concept", None))
        matched_norm = normalize_concept(matched) if matched else None

        if cur_norm and matched_norm:
            if matched_norm != cur_norm and matched:
                session.current_concept = matched[:500]
                await session.save()
            return
        if cur_norm and not matched_norm:
            return
        if not cur_norm and matched:
            session.current_concept = matched[:500]
            await session.save()

    @staticmethod
    def _remember_learned_concept(session: Session, concept: str | None) -> None:
        """
        Keep `session.learned_concepts` normalized (trim + lowercase).
        Adds only when concept is non-empty and not already present.
        """
        nc = normalize_concept(concept)
        if nc is None:
            return
        nc_norm = str(nc).strip().lower()
        if not nc_norm:
            return

        learned = list(getattr(session, "learned_concepts", None) or [])
        learned_norm_set = {
            str(x).strip().lower() for x in learned if x is not None and str(x).strip()
        }
        if nc_norm in learned_norm_set:
            return
        session.learned_concepts = learned + [nc_norm]

    async def _create_new_learning_session(
        self,
        student_id: PydanticObjectId,
        topic: Topic,
        *,
        curriculum_class_id: Optional[str] = None,
        curriculum_subject_id: Optional[str] = None,
        student_organization_id: Optional[PydanticObjectId] = None,
        runtime_curriculum_manifest: Optional[RuntimeCurriculumManifest] = None,
    ) -> Session:
        topic_id = topic.id
        ccid = (curriculum_class_id or "").strip() or None
        csid = (curriculum_subject_id or "").strip() or None
        if runtime_curriculum_manifest is not None:
            key_concepts = list(runtime_curriculum_manifest.key_concepts)
            concept_clusters = runtime_curriculum_manifest.concept_clusters
            from app.services.session_concept_tracking import session_manifest_concept_ids

            key_concept_ids = session_manifest_concept_ids(runtime_curriculum_manifest)
        else:
            key_concepts, concept_clusters = await self._resolve_key_concepts_for_topic(
                topic,
                curriculum_class_id=ccid,
                curriculum_subject_id=csid,
            )
            key_concept_ids = []
        eff_org = self._effective_session_organization_id(
            topic, student_organization_id
        )
        if eff_org is None:
            raise ValueError(
                "Cannot start session: user organization is required for catalog topics"
            )
        session_data: dict[str, Any] = {
            "organization_id": eff_org,
            "student_id": student_id,
            "topic_id": topic_id,
            "subject_id": topic.subject_id,
            "mode": "explorer",
            "ai_model_used": Settings.DEEPSEEK_MODEL,
            "start_time": datetime.utcnow(),
            "completion_status": "in_progress",
            "curriculum_class_id": ccid,
            "curriculum_subject_id": csid,
            "key_concepts": key_concepts,
            "key_concept_ids": key_concept_ids,
            "concept_clusters": concept_clusters,
            "current_concept_index": 0,
            "total_concepts": len(key_concepts),
            "flow_state": "idle",
            "sus_score": 50.0,
            # Cluster vs Topic taught_points separation for correct teachback and clarity gate
            "cluster_taught_points": [],
            "topic_taught_points": [],
        }
        if key_concepts:
            session_data["current_concept"] = key_concepts[0][:500]
        if key_concept_ids:
            session_data["current_concept_id"] = key_concept_ids[0]
        session = await self.session_repository.insert_in_progress_session_or_return_existing(
            session_data
        )
        if runtime_curriculum_manifest is not None:
            from app.services.progression.plan_progress_coordinator import (
                PlanProgressCoordinator,
            )

            await PlanProgressCoordinator().ensure_on_session_start(
                session, manifest=runtime_curriculum_manifest
            )
        return session

    async def _create_new_learning_session_teacher_topic(
        self,
        student_id: PydanticObjectId,
        tt: TeacherTopic,
        *,
        curriculum_class_id: Optional[str] = None,
        curriculum_subject_id: Optional[str] = None,
        runtime_curriculum_manifest: Optional[RuntimeCurriculumManifest] = None,
    ) -> Session:
        ccid = (curriculum_class_id or "").strip() or None
        csid = (curriculum_subject_id or "").strip() or None
        if runtime_curriculum_manifest is not None:
            key_concepts = list(runtime_curriculum_manifest.key_concepts)
            concept_clusters = runtime_curriculum_manifest.concept_clusters
            from app.services.session_concept_tracking import session_manifest_concept_ids

            key_concept_ids = session_manifest_concept_ids(runtime_curriculum_manifest)
        else:
            kc_raw = [
                str(c).strip()
                for c in (tt.key_concepts or [])
                if c is not None and str(c).strip()
            ]
            key_concepts = kc_raw if kc_raw else ["introduction"]
            concept_clusters = tt.concept_clusters
            key_concept_ids = []
        subj_oid = await self._curriculum_subject_oid_for_teacher_topic(tt)
        session_data: dict[str, Any] = {
            "organization_id": tt.organization_id,
            "student_id": student_id,
            "topic_id": tt.id,
            "subject_id": subj_oid,
            "mode": "explorer",
            "ai_model_used": Settings.DEEPSEEK_MODEL,
            "start_time": datetime.utcnow(),
            "completion_status": "in_progress",
            "curriculum_class_id": ccid,
            "curriculum_subject_id": csid,
            "key_concepts": key_concepts,
            "key_concept_ids": key_concept_ids,
            "concept_clusters": concept_clusters,
            "current_concept_index": 0,
            "total_concepts": len(key_concepts),
            "flow_state": "idle",
            "sus_score": 50.0,
            # Cluster vs Topic taught_points separation for correct teachback and clarity gate
            "cluster_taught_points": [],
            "topic_taught_points": [],
        }
        if key_concepts:
            session_data["current_concept"] = key_concepts[0][:500]
        if key_concept_ids:
            session_data["current_concept_id"] = key_concept_ids[0]
        session = await self.session_repository.insert_in_progress_session_or_return_existing(
            session_data
        )
        if runtime_curriculum_manifest is not None:
            from app.services.progression.plan_progress_coordinator import (
                PlanProgressCoordinator,
            )

            await PlanProgressCoordinator().ensure_on_session_start(
                session, manifest=runtime_curriculum_manifest
            )
        return session

    async def continue_session_for_topic(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        *,
        student_organization_id: Optional[PydanticObjectId] = None,
    ) -> Session:
        """Return existing in-progress session for this topic (no create)."""
        topic = await self._get_topic_or_teacher_topic(topic_id)
        if topic is None:
            raise ValueError("Topic not found")
        org_id = self._effective_session_organization_id(
            topic, student_organization_id
        )
        if org_id is None:
            raise ValueError(
                "Cannot continue session: user organization is required for catalog topics"
            )
        existing = await self.session_repository.get_student_active_session_for_topic(
            student_id,
            topic_id,
            organization_id=org_id,
        )
        if existing is None:
            raise ValueError("No active session for this topic")
        return existing

    async def restart_session_for_topic(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        *,
        curriculum_class_id: Optional[str] = None,
        curriculum_subject_id: Optional[str] = None,
        student_organization_id: Optional[PydanticObjectId] = None,
        runtime_curriculum_manifest: Optional[RuntimeCurriculumManifest] = None,
    ) -> Session:
        """Mark prior in-progress session for this topic completed (no post pipeline), then create a new session."""
        topic = await self._get_topic_or_teacher_topic(topic_id)
        if topic is None:
            raise ValueError("Topic not found")
        org_id = self._effective_session_organization_id(
            topic, student_organization_id
        )
        if org_id is None:
            raise ValueError(
                "Cannot restart session: user organization is required for catalog topics"
            )
        existing = await self.session_repository.get_student_active_session_for_topic(
            student_id,
            topic_id,
            organization_id=org_id,
        )
        if existing is not None:
            await self.session_repository.end_session(existing.id)
        if isinstance(topic, TeacherTopic):
            return await self._create_new_learning_session_teacher_topic(
                student_id,
                topic,
                curriculum_class_id=curriculum_class_id,
                curriculum_subject_id=curriculum_subject_id,
                runtime_curriculum_manifest=runtime_curriculum_manifest,
            )
        return await self._create_new_learning_session(
            student_id,
            topic,
            curriculum_class_id=curriculum_class_id,
            curriculum_subject_id=curriculum_subject_id,
            student_organization_id=student_organization_id,
            runtime_curriculum_manifest=runtime_curriculum_manifest,
        )

    async def start_session(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        *,
        action: Optional[str] = None,
        curriculum_class_id: Optional[str] = None,
        curriculum_subject_id: Optional[str] = None,
        student_organization_id: Optional[PydanticObjectId] = None,
        runtime_curriculum_manifest: Optional[RuntimeCurriculumManifest] = None,
    ) -> Session | dict[str, Any]:
        """
        Start or resume flow for a topic. At most one in-progress (active) session per (student, topic).
        action=None: if active exists, return resume_prompt dict; else create session.
        action=continue: return existing active session for topic.
        action=restart: complete existing without summary pipeline, create new session.
        """
        topic = await self._get_topic_or_teacher_topic(topic_id)
        if topic is None:
            raise ValueError("Topic not found")

        act = (action or "").strip().lower() or None
        if act == "continue":
            return await self.continue_session_for_topic(
                student_id,
                topic_id,
                student_organization_id=student_organization_id,
            )
        if act == "restart":
            return await self.restart_session_for_topic(
                student_id,
                topic_id,
                curriculum_class_id=curriculum_class_id,
                curriculum_subject_id=curriculum_subject_id,
                student_organization_id=student_organization_id,
                runtime_curriculum_manifest=runtime_curriculum_manifest,
            )

        org_id = self._effective_session_organization_id(
            topic, student_organization_id
        )
        if org_id is None:
            raise ValueError(
                "Cannot start session: user organization is required for catalog topics"
            )
        active = await self.session_repository.get_student_active_session_for_topic(
            student_id,
            topic_id,
            organization_id=org_id,
        )
        if active is not None:
            return {
                "type": "resume_prompt",
                "message": "You have an ongoing session for this topic.",
                "buttons": ["continue", "restart"],
                "session_id": str(active.id),
            }
        if isinstance(topic, TeacherTopic):
            return await self._create_new_learning_session_teacher_topic(
                student_id,
                topic,
                curriculum_class_id=curriculum_class_id,
                curriculum_subject_id=curriculum_subject_id,
                runtime_curriculum_manifest=runtime_curriculum_manifest,
            )
        return await self._create_new_learning_session(
            student_id,
            topic,
            curriculum_class_id=curriculum_class_id,
            curriculum_subject_id=curriculum_subject_id,
            student_organization_id=student_organization_id,
            runtime_curriculum_manifest=runtime_curriculum_manifest,
        )

    async def get_active_session_for_topic(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        *,
        student_organization_id: Optional[PydanticObjectId] = None,
    ) -> Optional[Session]:
        """Return in-progress session for this student and topic, or None."""
        topic = await self._get_topic_or_teacher_topic(topic_id)
        if topic is None:
            return None
        org_id = self._effective_session_organization_id(
            topic, student_organization_id
        )
        if org_id is None:
            return None
        return await self.session_repository.get_student_active_session_for_topic(
            student_id,
            topic_id,
            organization_id=org_id,
        )

    async def end_session(
        self, session_id: PydanticObjectId
    ) -> tuple[Optional[Session], Optional[list[dict[str, Any]]]]:
        """Mark session completed and run mastery, recommendations, summary/notes (idempotent).

        Returns ``(session, recommended_topics)``. ``recommended_topics`` is ``None`` when
        the recommendation step did not run or failed; otherwise a list (possibly empty).
        """
        existing = await self.session_repository.get_by_id(session_id)
        if existing is None:
            return None, None
        if existing.completion_status != "in_progress":
            return existing, None

        updated = await self.session_repository.end_session(session_id)
        if updated is None:
            return None, None

        recommended_topics: Optional[list[dict[str, Any]]] = None

        if self.mastery_service is not None:
            try:
                await self.mastery_service.calculate_mastery_for_session(session_id)
            except Exception as e:
                logger.exception(
                    "Mastery calculation failed for session_id=%s: %s",
                    session_id,
                    e,
                )
            if self.recommendation_service is not None:
                try:
                    recommended_topics = await self.recommendation_service.recommend_next_topics(
                        student_id=updated.student_id,
                        topic_id=updated.topic_id,
                    )
                except Exception as e:
                    logger.exception(
                        "Recommendation failed for session_id=%s: %s",
                        session_id,
                        e,
                    )

        try:
            await self._generate_summary_and_reusable_note(updated)
        except Exception as e:
            logger.exception(
                "Post-session content generation failed for session_id=%s: %s",
                session_id,
                e,
            )

        return updated, recommended_topics

    async def _generate_summary_and_reusable_note(self, session: Session) -> None:
        """Generate personal session summary and reusable detailed note (if missing)."""
        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )
        event_repository = EventRepository()

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

        events = await event_repository.get_session_events(session.id, limit=500)
        # If the student ended the session without sending any messages/questions,
        # skip all post-session generation (summary, detailed notes, and assignments).
        has_student_interaction = any(
            e.event_type in (SessionEventType.QUESTION, SessionEventType.ANSWER)
            for e in (events or [])
        )
        if not has_student_interaction:
            logger.info(
                "Skipping post-session generation for session_id=%s (no QUESTION/ANSWER events).",
                session.id,
            )
            return
        mastery = await MasteryRecord.find_one(
            mastery_record_filter(
                session.organization_id,
                session.student_id,
                session.topic_id,
                normalize_concept(getattr(session, "current_concept", None)),
            )
        )
        events_text = self._build_events_snapshot(events)

        topic_id = session.topic_id
        topic = await self._get_topic_or_teacher_topic(topic_id)

        mastery_text = (
            f"mastery_score={mastery.mastery_score}, engagement_score={mastery.engagement_score}, "
            f"revision_needed={mastery.revision_needed}, attempt_count={mastery.attempt_count}"
            if mastery is not None
            else "mastery data not available"
        )
        topic_name = (
            (getattr(topic, "topic_name", None) or "Unknown topic")
            if topic is not None
            else "Unknown topic"
        )
        session_interaction = (
            f"Events snapshot:\n{events_text}\n\nMastery data:\n{mastery_text}"
        )
        try:
            summary_data = await self._generate_session_summary(
                topic_name=topic_name,
                session_interaction=session_interaction,
            )
        except Exception:
            summary_data = {
                "summary": "Session completed.",
                "key_points": [],
                "mistakes": [],
                "strengths": [],
                "recommendations": [],
            }

        summary_body = (summary_data.get("summary") or "").strip()
        recs = summary_data.get("recommendations") or []
        if isinstance(recs, list) and recs:
            rec_line = "; ".join(
                str(x).strip() for x in recs[:20] if str(x).strip()
            )
            if rec_line:
                summary_body = (
                    summary_body + "\n\nRecommendations: " + rec_line
                ).strip()
        if not summary_body:
            summary_body = "Session completed."
        summary_text = summary_body[:2000]

        key_points_learned = self._normalize_summary_str_list(
            summary_data.get("key_points"), 50
        )
        mistakes_identified = self._normalize_summary_str_list(
            summary_data.get("mistakes"), 50
        )
        strengths_identified = self._normalize_summary_str_list(
            summary_data.get("strengths"), 50
        )

        await SessionSummary(
            organization_id=session.organization_id,
            student_id=session.student_id,
            session_id=session.id,
            topic_id=session.topic_id,
            summary_text=summary_text,
            key_points_learned=key_points_learned,
            mistakes_identified=mistakes_identified,
            strengths_identified=strengths_identified,
            ai_model_used=session.ai_model_used,
        ).insert()

        existing_note = await TopicNote.find_one(
            {
                "topic_id": topic_id,
                "organization_id": session.organization_id,
                "note_type": "detailed",
                "teaching_style": teaching_style,
                "interest_category": interest_category,
                "difficulty_level": difficulty_level,
                "approved": True,
            }
        )
        if existing_note is None:
            notes = await rag_service.get_topic_notes(
                topic_id=topic_id,
                organization_id=session.organization_id,
                teaching_style=teaching_style,
                interest_category=interest_category,
                difficulty_level=difficulty_level,
                current_concept=getattr(session, "current_concept", None),
                curriculum_class_id=getattr(session, "curriculum_class_id", None),
                curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
            )
            context = await rag_service.build_context(
                notes,
                topic_id=topic_id,
                organization_id=session.organization_id,
                curriculum_class_id=getattr(session, "curriculum_class_id", None),
                curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
            )
            if context and len(context.strip()) >= 50:
                detailed_note_text = await rag_service.generate_prompt(
                    question="Generate detailed study notes for this topic.",
                    context=context,
                    student_profile=student_profile.model_dump()
                    if student_profile
                    else None,
                    topic_name=topic.topic_name if topic else None,
                    learning_state=getattr(session, "learning_state", "explaining"),
                    user_intent="NOTE_GENERATION",
                    last_answer=None,
                    is_followup=False,
                    current_concept=getattr(session, "current_concept", None),
                )

                if topic is None:
                    raise ValueError("Topic not found while creating reusable note")

                grade = (
                    getattr(student_profile, "grade", None)
                    if student_profile
                    else None
                )
                board = (
                    getattr(student_profile, "board", None)
                    if student_profile
                    else None
                )
                if not grade:
                    grade = "unknown"
                if not board:
                    board = "general"

                duplicate_filters = {
                    "topic_id": topic_id,
                    "organization_id": session.organization_id,
                    "note_type": "detailed",
                    "teaching_style": teaching_style,
                    "interest_category": interest_category,
                    "difficulty_level": difficulty_level,
                    "approved": True,
                }
                existing = await topic_note_repository.get_one(
                    filters=duplicate_filters
                )
                if existing is None:
                    await TopicNote(
                        organization_id=session.organization_id,
                        topic_id=topic_id,
                        grade=grade,
                        board=board,
                        note_type="detailed",
                        content_markdown=detailed_note_text,
                        source_type="ai",
                        teaching_style=teaching_style,
                        interest_category=interest_category,
                        difficulty_level=difficulty_level,
                        approved=True,
                        usage_count=0,
                    ).insert()

        await self._generate_assignment(session, student_profile, mastery)

    @staticmethod
    def _normalize_summary_str_list(
        value: Any,
        max_items: int,
        max_item_len: int = 500,
    ) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for x in value[:max_items]:
            s = str(x).strip()
            if s:
                out.append(s[:max_item_len])
        return out

    def _build_events_snapshot(self, events: list[SessionEvent]) -> str:
        """Build short textual event summary for LLM context."""
        if not events:
            return "no events recorded"
        lines: list[str] = []
        for e in events[:50]:
            content = (e.content or "").strip()
            lines.append(
                f"- {e.event_type}: correct={e.is_correct}, response_time_ms={e.response_time_ms}, content={content[:120]}"
            )
        return "\n".join(lines)

    def _empty_summary_dict(self, summary: str) -> dict:
        return {
            "summary": summary,
            "key_points": [],
            "mistakes": [],
            "strengths": [],
            "recommendations": [],
        }

    async def _generate_session_summary(
        self,
        topic_name: str,
        session_interaction: str,
    ) -> dict:
        prompt = f"""
You are an expert AI tutor.

Analyze the following learning session and generate a structured summary.

Topic: {topic_name}

Session Interaction:
{session_interaction}

---

Return STRICT JSON:

{{
"summary": "Short paragraph summarizing what the student learned",
"key_points": ["list of key concepts learned"],
"mistakes": ["list of mistakes or misunderstandings"],
"strengths": ["what the student did well"],
"recommendations": ["what the student should study next"]
}}

---

Rules:

* Always return valid JSON
* Do not add explanation outside JSON
* Keep points concise but meaningful
* If no mistakes, return empty array []
* If limited interaction, still infer basic learning

---
"""
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return self._empty_summary_dict(
                "Session completed. Summary unavailable (AI not configured)."
            )

        url = Settings.DEEPSEEK_API_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": Settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "You are an expert AI tutor."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "thinking": DEEPSEEK_THINKING_DISABLED,
        }

        async with httpx.AsyncClient(timeout=60.0, http2=False) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except Exception:
                return self._empty_summary_dict(
                    "Session completed. Summary could not be generated due to AI timeout."
                )

        if response.status_code != 200:
            return self._empty_summary_dict(
                "Session completed. Summary unavailable."
            )

        try:
            api_data = response.json()
            ai_output = api_data["choices"][0]["message"]["content"]
        except Exception:
            return self._empty_summary_dict("Session completed successfully.")

        clean_output = ai_output.strip()
        if clean_output.startswith("```"):
            clean_output = re.sub(
                r"^```(?:json)?\s*",
                "",
                clean_output,
                flags=re.IGNORECASE,
            )
            clean_output = re.sub(r"\s*```\s*$", "", clean_output).strip()

        try:
            data = json.loads(clean_output)
            summary = str(data.get("summary", "")).strip()
            if not summary:
                summary = "Session completed successfully."
            return {
                "summary": summary,
                "key_points": data.get("key_points") or [],
                "mistakes": data.get("mistakes") or [],
                "strengths": data.get("strengths") or [],
                "recommendations": data.get("recommendations") or [],
            }
        except Exception:
            return {
                "summary": (clean_output[:500] if clean_output else "Session completed."),
                "key_points": [],
                "mistakes": [],
                "strengths": [],
                "recommendations": [],
            }

    @staticmethod
    def _strip_json_fence(ai_output: str) -> str:
        clean_output = ai_output.strip()
        if clean_output.startswith("```"):
            clean_output = re.sub(
                r"^```(?:json)?\s*",
                "",
                clean_output,
                flags=re.IGNORECASE,
            )
            clean_output = re.sub(r"\s*```\s*$", "", clean_output).strip()
        return clean_output

    async def _deepseek_chat_completion(
        self,
        user_content: str,
        *,
        system_content: str = "You are an expert tutor.",
        temperature: float = 0.4,
        timeout: float = 60.0,
    ) -> Optional[str]:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        url = Settings.DEEPSEEK_API_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": Settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "thinking": DEEPSEEK_THINKING_DISABLED,
        }
        async with httpx.AsyncClient(timeout=timeout, http2=False) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except Exception:
                return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except Exception:
            return None

    async def _generate_assignment_questions_ai(
        self,
        topic_name: str,
        difficulty: str,
        count: int,
    ) -> List[str]:
        if count <= 0:
            return []
        prompt = f"""
Generate exactly {count} distinct short-answer practice questions for the topic below.

Topic: {topic_name}
Difficulty: {difficulty}

Return STRICT JSON:
{{"questions": ["question 1", "question 2"]}}

Rules:
* Only the JSON object, no markdown outside JSON
* Questions must be answerable in 1–3 sentences
"""
        raw = await self._deepseek_chat_completion(
            prompt,
            system_content="You are an expert tutor who writes clear assessment items.",
            temperature=0.5,
        )
        if not raw:
            return []
        clean = self._strip_json_fence(raw)
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            return []
        qs = data.get("questions")
        if not isinstance(qs, list):
            return []
        out: List[str] = []
        for x in qs[:count]:
            s = str(x).strip()
            if s:
                out.append(s)
        return out

    async def _generate_assignment(
        self,
        session: Session,
        student_profile: Optional[StudentProfile],
        mastery_record: Optional[MasteryRecord],
    ) -> None:
        topic_id = session.topic_id
        organization_id = session.organization_id
        student_id = session.student_id

        mastery_score = (
            float(mastery_record.mastery_score)
            if mastery_record is not None
            else 50.0
        )

        topic = await self._get_topic_or_teacher_topic(topic_id)
        topic_name = (
            getattr(topic, "topic_name", None) or "Unknown topic"
            if topic is not None
            else "Unknown topic"
        )

        event_repository = EventRepository()
        events = await event_repository.get_many(
            filters={
                "session_id": session.id,
                "event_type": SessionEventType.ANSWER,
            },
            limit=50,
        )
        mistakes = [
            e.content
            for e in events
            if hasattr(e, "is_correct")
            and e.is_correct is False
            and e.content
        ]

        mistakes_text = "; ".join(m[:500] for m in mistakes if m) or "none recorded"

        profile_hint = ""
        if student_profile is not None and getattr(student_profile, "interests", None):
            profile_hint = (
                "\nStudent interests (optional context): "
                + ", ".join(student_profile.interests[:8])
            )

        plan_prompt = f"""
You are an expert tutor.

Decide whether the student needs an assignment.

Topic: {topic_name}
Mastery Score: {mastery_score}
Mistakes: {mistakes_text}
{profile_hint}

Return STRICT JSON:

{{
"assign": true,
"difficulty": "easy",
"focus_concepts": ["..."],
"num_questions": 3
}}

Rules:

* If mastery < 50 → assign = true
* If mistakes exist → assign = true
* If mastery > 80 and no mistakes → assign = false
* difficulty must be "easy", "medium", or "hard"
* num_questions must be an integer from 3 to 5
* Output only valid JSON, no other text
"""

        raw_plan = await self._deepseek_chat_completion(
            plan_prompt,
            system_content="You are an expert tutor. Reply with JSON only.",
            temperature=0.3,
        )
        if not raw_plan:
            return

        clean_plan = self._strip_json_fence(raw_plan)
        try:
            plan = json.loads(clean_plan)
        except json.JSONDecodeError:
            return

        should_assign = bool(plan.get("assign"))
        if mastery_score < 50.0 or mistakes:
            should_assign = True
        if mastery_score > 80.0 and not mistakes:
            should_assign = False
        if not should_assign:
            return

        raw_diff = plan.get("difficulty") or "medium"
        difficulty: Literal["easy", "medium", "hard"]
        if raw_diff in ("easy", "medium", "hard"):
            difficulty = cast(Literal["easy", "medium", "hard"], raw_diff)
        else:
            difficulty = "medium"

        num_raw = plan.get("num_questions", 3)
        try:
            num_questions = int(num_raw)
        except (TypeError, ValueError):
            num_questions = 3
        num_questions = max(3, min(5, num_questions))

        focus_raw = plan.get("focus_concepts") or []
        focus_concepts: List[str] = []
        if isinstance(focus_raw, list):
            focus_concepts = [
                str(x).strip()[:200] for x in focus_raw[:20] if str(x).strip()
            ]

        topic_question_repository = TopicQuestionRepository()
        base_filters: dict = {
            "topic_id": topic_id,
            "organization_id": organization_id,
            "approved": True,
        }
        if difficulty == "easy":
            diff_filter: str | dict = {"$in": ["basic"]}
        elif difficulty == "medium":
            diff_filter = "medium"
        else:
            diff_filter = {"$in": ["hard"]}

        bank_filters = {**base_filters, "difficulty_level": diff_filter}
        bank_questions = await topic_question_repository.get_many(
            filters=bank_filters,
            limit=50,
        )
        if not bank_questions:
            bank_questions = await topic_question_repository.get_many(
                filters=base_filters,
                limit=50,
            )

        random.shuffle(bank_questions)

        selected_payload: List[dict] = []
        for q in bank_questions[:num_questions]:
            selected_payload.append(
                {
                    "source": "bank",
                    "question_id": str(q.id),
                    "question_text": q.question_text,
                    "difficulty_level": q.difficulty_level,
                    "correct_answer": q.correct_answer,
                }
            )

        need = num_questions - len(selected_payload)
        if need > 0:
            ai_qs = await self._generate_assignment_questions_ai(
                topic_name, difficulty, need
            )
            for text in ai_qs:
                if text.strip():
                    selected_payload.append(
                        {"source": "ai", "question_text": text.strip()[:5000]}
                    )

        if not selected_payload:
            return

        await SessionAssignment(
            organization_id=organization_id,
            student_id=student_id,
            topic_id=topic_id,
            session_id=session.id,
            questions=selected_payload,
            difficulty_level=difficulty,
            status="pending",
            score=None,
            focus_concepts=focus_concepts,
        ).insert()

        logger.info("Assignment generated for student %s", student_id)

    async def evaluate_assignment(
        self,
        assignment_id: str,
        student_id: str,
        answers: list,
    ) -> dict:
        try:
            assignment_oid = PydanticObjectId(assignment_id)
            student_oid = PydanticObjectId(student_id)
        except Exception:
            raise ValueError("Invalid assignment_id or student_id")

        assignment = await SessionAssignment.get(assignment_oid)
        if assignment is None:
            raise ValueError("Assignment not found")
        if assignment.student_id != student_oid:
            raise ValueError("Assignment does not belong to this student")

        if getattr(assignment, "status", None) == "completed":
            raise ValueError("Assignment already completed")

        if not isinstance(answers, list):
            raise ValueError("answers must be a list")

        mastery_service = self.mastery_service

        topic_question_repository = TopicQuestionRepository()
        questions = assignment.questions if isinstance(assignment.questions, list) else []
        total = len(questions)
        if total == 0:
            assignment.status = "completed"
            assignment.score = 0.0
            await assignment.save()
            return {"score": 0.0, "correct": 0, "total": 0}

        correct_count = 0
        evaluation_results: List[dict] = []

        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                continue

            user_answer_raw = answers[idx] if idx < len(answers) else ""
            if isinstance(user_answer_raw, dict):
                user_answer = str(user_answer_raw.get("answer", "")).strip()
            else:
                user_answer = str(user_answer_raw).strip()

            question_text = str(q.get("question_text", "")).strip()
            correct_answer = q.get("correct_answer")

            if (not correct_answer) and q.get("source") == "bank" and q.get("question_id"):
                try:
                    qid = PydanticObjectId(str(q.get("question_id")))
                    bank_q = await topic_question_repository.get_by_id(qid)
                    if bank_q is not None and getattr(bank_q, "correct_answer", None):
                        correct_answer = bank_q.correct_answer
                except Exception:
                    pass

            eval_prompt = f"""
You are evaluating a student's answer.

Question: {question_text}
Correct Answer: {str(correct_answer or "").strip()}
Student Answer: {user_answer}

Return STRICT JSON:
{{
"correct": true/false,
"feedback": "short explanation"
}}
"""
            ai_eval_raw = await self._deepseek_chat_completion(
                eval_prompt,
                system_content="You are an expert tutor. Reply with JSON only.",
                temperature=0.2,
            )
            is_correct = False
            feedback = "Keep practicing."
            if ai_eval_raw:
                cleaned = self._strip_json_fence(ai_eval_raw)
                try:
                    eval_data = json.loads(cleaned)
                    is_correct = bool(eval_data.get("correct", False))
                    parsed_feedback = str(eval_data.get("feedback", "")).strip()
                    if parsed_feedback:
                        feedback = parsed_feedback[:500]
                except Exception:
                    is_correct = False
                    feedback = "Keep practicing."

            if is_correct:
                correct_count += 1

            question_result = {
                "question_index": idx,
                "is_correct": is_correct,
                "student_answer": user_answer,
                "feedback": feedback,
            }
            evaluation_results.append(question_result)
            q["evaluation"] = question_result

            if mastery_service is not None:
                await mastery_service.update_mastery(
                    student_id=assignment.student_id,
                    topic_id=assignment.topic_id,
                    concept=None,
                    is_correct=is_correct,
                    organization_id=assignment.organization_id,
                )

        score = round((correct_count / total) * 100.0, 2) if total > 0 else 0.0
        assignment.status = "completed"
        assignment.score = score
        assignment.questions = questions
        await assignment.save()

        return {
            "score": score,
            "correct": correct_count,
            "total": total,
            "results": evaluation_results,
        }

    async def _generate_tutor_rag_reply(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        topic_id: PydanticObjectId,
        intent: str,
        state_at_entry: str,
        topic_for_prompt: "Topic | TeacherTopic | None",
        rag_service: RAGService,
        context: str,
        student_profile: "StudentProfile | None",
        event_repository: EventRepository,
    ) -> str:
        """Delegates to explanation_handler.generate_tutor_rag_reply."""
        return await _explain_generate_rag_reply(
            session,
            session_id,
            student_id,
            question,
            topic_id,
            intent,
            state_at_entry,
            topic_for_prompt,
            rag_service,
            context,
            student_profile,
            event_repository,
        )

    async def _teacher_explain_turn(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        topic: "Topic | TeacherTopic",
        rag_question: str,
        *,
        intent: str,
        state_at_entry: str,
        next_flow_state: str,
        next_learning_state: "str | None",
    ) -> "str | dict | None":
        """Delegates to explanation_handler.teacher_explain_turn via HandlerContext."""
        ctx = self._build_handler_context()
        return await _explain_teacher_explain_turn(
            ctx,
            session,
            session_id,
            student_id,
            topic,
            rag_question,
            intent=intent,
            state_at_entry=state_at_entry,
            next_flow_state=next_flow_state,
            next_learning_state=next_learning_state,
        )

    async def _teacher_advance_skip(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        topic: "Topic | TeacherTopic",
    ) -> dict:
        """Delegates to explanation_handler.teacher_advance_skip via HandlerContext."""
        ctx = self._build_handler_context()
        return await _explain_teacher_advance_skip(ctx, session, session_id, student_id, topic)

    async def _generate_and_return_quiz(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
    ) -> dict:
        """Delegates to quiz_handler.generate_and_return_quiz via HandlerContext."""
        ctx = self._build_handler_context()
        return await _quiz_generate_and_return(ctx, session, session_id, student_id)

    async def _generate_and_return_cluster_quiz(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
    ) -> dict:
        ctx = self._build_handler_context()
        return await _quiz_generate_cluster_and_return(ctx, session, session_id, student_id)

    async def _teacher_handle_conversation(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        topic: Topic | TeacherTopic | None,
        is_quiz_mode: bool,
    ) -> str | dict | None:
        if not self._is_teacher_progression(session) or topic is None:
            return None
        flow = getattr(session, "flow_state", "idle") or "idle"
        self._teacher_debug_flow(session, topic)

        if flow == "completed":
            return {
                "type": "completed",
                "message": "Great job! You completed this topic.",
            }

        if is_quiz_mode or flow == "quizzing":
            return None

        flow = getattr(session, "flow_state", "idle") or "idle"
        # Zone 2 uses VTSE like Zone 1 — recover legacy zone_2_entry parking.
        if flow == "zone_2_entry":
            session.flow_state = "idle"
            await session.save()
            flow = "idle"

        action = self._teacher_flow_action(question)
        intent_plain = self._classify_intent(question.strip().lower(), False)
        if action is None and intent_plain == "CONFIRM":
            if flow != "concept_questions" and not is_concept_questions_mode(session):
                action = "understand"

        # ── Pedagogy introduction cards (before Zone 0 / all teaching) ────────
        from app.services.pedagogy.pedagogy_intro_service import PedagogyIntroService
        from app.services.pedagogy.pedagogy_recall_curiosity_service import (
            PedagogyRecallCuriosityService,
        )

        _pedagogy = PedagogyIntroService()
        _pedagogy_result = await _pedagogy.maybe_emit(session, action=action)
        if _pedagogy_result is not None:
            if _pedagogy_result.get("type") != "noop":
                await _pedagogy.apply_flow_state(session, _pedagogy_result)
            return _pedagogy_result

        _recall_curiosity = PedagogyRecallCuriosityService()
        _rc_result = await _recall_curiosity.maybe_emit(
            session, action=action, question=question
        )
        if _rc_result is not None:
            if _rc_result.get("type") != "noop":
                await _recall_curiosity.apply_flow_state(session, _rc_result)
            return _rc_result

        _pedagogy_result2 = await _pedagogy.maybe_emit(session, action=action)
        if _pedagogy_result2 is not None:
            if _pedagogy_result2.get("type") != "noop":
                await _pedagogy.apply_flow_state(session, _pedagogy_result2)
            return _pedagogy_result2

        _rc_result2 = await _recall_curiosity.maybe_emit(
            session, action=action, question=question
        )
        if _rc_result2 is not None:
            if _rc_result2.get("type") != "noop":
                await _recall_curiosity.apply_flow_state(session, _rc_result2)
            return _rc_result2

        # Pedagogy handlers may have updated flow_state — refresh local flow.
        flow = getattr(session, "flow_state", "idle") or "idle"

        # ── Concept teaching orchestration (Story Hook around VTSE) ───────────
        from app.services.pedagogy.concept_teaching_orchestrator import (
            ConceptTeachingOrchestrator,
        )

        _cto = ConceptTeachingOrchestrator()
        _cto_result = await _cto.maybe_emit(
            session,
            action=action,
            handler_ctx=self._build_handler_context(),
            session_id=session_id,
            student_id=student_id,
            topic=topic,
            user_input=question,
        )
        if _cto_result is not None:
            if _cto_result.get("type") != "noop":
                await _cto.apply_flow_state(session, _cto_result)
                return _cto_result
            return _cto_result

        # Concept teaching may have returned None after story_hook_done → VTSE next.
        flow = getattr(session, "flow_state", "idle") or "idle"

        from app.services.progression.zone_transition_coordinator import (
            ZoneTransitionCoordinator,
        )

        _zone_entry = ZoneTransitionCoordinator.parse_zone_entry_flow(flow)
        if _zone_entry is not None:
            return ZoneTransitionCoordinator.zone_entry_payload(_zone_entry)

        # ── Flow checkpoint runtime (flow_vertical_process orchestration) ─────
        if action and (
            action.startswith("flow_checkpoint_pause")
            or action.startswith("flow_checkpoint_continue")
            or action.startswith("flow_checkpoint_question")
        ):
            _fc_again = await maybe_dispatch_flow_checkpoint(
                self._build_handler_context(),
                session,
                session_id,
                student_id,
                topic,
                question,
            )
            if _fc_again is not None:
                return _fc_again
            if action.startswith("flow_checkpoint_pause"):
                labels, count, tid = parse_flow_checkpoint_pause_request(question)
                return await handle_flow_checkpoint_pause(
                    session,
                    labels=labels,
                    completed_node_count=count,
                    timeline_id=tid,
                )
            if action.startswith("flow_checkpoint_continue"):
                return await handle_flow_checkpoint_continue(
                    session,
                    expected_timeline_id=parse_flow_checkpoint_continue_timeline(question),
                )

        # ── Post-concept LLM notes (after concept check, before next concept) ──
        if is_concept_notes_mode(session):
            if action == "concept_notes_continue":
                _ctx_notes = self._build_handler_context()
                return await handle_concept_notes_continue(
                    _ctx_notes,
                    session,
                    session_id,
                    student_id,
                    topic,
                )
            return {"type": "noop"}

        # ── Zone 1 concept questions (post-VTSE) — before flow-checkpoint noop ──
        if is_concept_questions_mode(session) or flow == "concept_questions":
            if action in ("quiz", "ready", "skip"):
                return {"type": "noop"}
            cq_action = normalize_concept_question_action(
                session,
                action=action,
                student_text=(question or ""),
            )
            _ctx_cq = self._build_handler_context()
            return await handle_concept_questions_dispatch(
                _ctx_cq,
                session,
                session_id,
                student_id,
                topic,
                student_text=(question or "").strip(),
                action=cq_action,
            )

        # ── Zone 1 cluster quiz (structured 3-question loop at cluster end) ──
        if is_cluster_quiz_mode(session) or flow == "cluster_quiz":
            if action in ("quiz", "ready", "skip"):
                return {"type": "noop"}
            cluster_action = normalize_cluster_quiz_action(
                session,
                action=action,
                student_text=(question or ""),
            )
            _ctx_cluster = self._build_handler_context()
            return await handle_cluster_quiz_dispatch(
                _ctx_cluster,
                session,
                session_id,
                student_id,
                topic,
                student_text=(question or "").strip(),
                action=cluster_action,
            )

        if bool(getattr(session, "flow_checkpoint_pending", False)):
            q_st = (question or "").strip()
            if action is None and q_st and not q_st.lower().startswith("__action:"):
                _ctx = self._build_handler_context()
                return await handle_flow_checkpoint_question(
                    _ctx, session, session_id, student_id, topic, q_st
                )
            if action is not None and action != "flow_checkpoint_continue" and not (
                action or ""
            ).startswith("flow_checkpoint_pause"):
                return {"type": "noop"}

        # Student-question loop guard: never allow quiz entry while active.
        if bool(getattr(session, "student_questions_active", False)) and action == "quiz":
            return {"type": "noop"}

        # Micro-teaching guard: if the tutor has already asked a pending in-chat
        # question for the current concept, never auto-advance/auto-quiz yet.
        # We must wait for the student's answer first.
        pending_micro_q = (getattr(session, "current_question", None) or "").strip()
        step = int(getattr(session, "current_step_in_concept", 0) or 0)
        ready_for_quiz = step >= MICRO_TEACH_STEP_READY_QUIZ
        if (
            action == "quiz"
            and not ready_for_quiz
            and flow in ("explaining", "checking_understanding")
        ):
            last_answer_text = (getattr(session, "last_answer", None) or "").strip()
            ends_with_question = bool(last_answer_text) and last_answer_text.rstrip().endswith("?")
            if pending_micro_q or ends_with_question:
                # Silent guard: returning visible text here can create a frontend
                # onComplete -> __action:quiz feedback loop.
                return {"type": "noop"}

        # ── Zone 0 pre-flight intercept ───────────────────────────────────────
        # Handle all Zone 0 flow states before any Zone 1+ logic runs.
        # These checks are mutually exclusive and each returns non-None, so
        # the rest of _teacher_handle_conversation is completely bypassed
        # during Zone 0, keeping Zones 1–4 fully isolated.
        # IMPORTANT: must NOT use "or 1" here — current_zone == 0 is falsy,
        # and "0 or 1" would evaluate to 1, skipping Zone 0 entirely.
        _cz = getattr(session, "current_zone", None)
        # Default 0 (Zone 0) when unset — "else 1" incorrectly skipped Zone 0 for
        # legacy documents missing current_zone and routed straight to Zone 1.
        _z0_zone = int(_cz) if _cz is not None else 0
        _z0_phase = str(getattr(session, "zone0_phase", "anchoring") or "anchoring")

        if (
            flow == "zone0_prereq"
            or flow == "zone0_curiosity"
            or flow == "zone0_mirror"
            or (flow == "idle" and _z0_zone == 0 and _z0_phase != "done")
        ):
            _z0_ctx = self._build_handler_context()

            if flow == "zone0_prereq":
                return await zone0_handle_prereq_answer(
                    _z0_ctx, session, session_id, student_id, question, topic
                )

            if flow == "zone0_curiosity":
                _z0p_cur = str(getattr(session, "zone0_phase", "") or "")
                if _z0p_cur == "curiosity_active":
                    _z0p_cur = "curiosity_wait"
                if _z0p_cur == "curiosity_wait":
                    if action == "zone0_ready":
                        return {"type": "noop"}
                    qin = (question or "").strip()
                    if not qin or qin == ".":
                        return {"type": "noop"}
                    if qin.lower().startswith("__action:"):
                        return {"type": "noop"}
                    return await zone0_after_curiosity_answer(
                        _z0_ctx,
                        session,
                        session_id,
                        student_id,
                        qin,
                        topic,
                    )
                if _z0p_cur == "curiosity_ready":
                    if action == "zone0_ready" or zone0_student_text_confirms_ready(
                        question
                    ):
                        return await zone0_complete_to_zone1(
                            _z0_ctx,
                            session,
                            session_id,
                            student_id,
                            topic,
                            student_thought=question,
                        )
                    return {"type": "noop"}
                return {"type": "noop"}

            # Mirror on board (curiosity_pending) — advance only via zone0_mirror_done.
            if _z0_phase == "curiosity_pending" or flow == "zone0_mirror":
                if action == "zone0_mirror_done" and _z0_phase == "curiosity_pending":
                    prior = (
                        getattr(session, "zone0_pending_anchor_reply", None) or ""
                    ).strip() or None
                    return await zone0_emit_curiosity(
                        _z0_ctx,
                        session,
                        session_id,
                        student_id,
                        topic,
                        prior_anchor_reply=prior,
                    )
                if action == "zone0_mirror_done":
                    logger.info(
                        "zone0_mirror_done ignored: zone0_phase=%s (expected curiosity_pending)",
                        _z0_phase,
                    )
                return {"type": "noop"}

            # flow == "idle" and zone == 0 and phase != "done"
            if action == "skip":
                return await zone0_skip(_z0_ctx, session, session_id, topic)
            # After anchor: stay on anchor until the student sends chat (or zone0_next).
            if _z0_phase == "anchor_wait":
                q_st = (question or "").strip()
                # "ok"/"yes"/… map to action "start" — must still advance past anchor.
                if action in ("zone0_next", "understand", "start") or (
                    action is None
                    and q_st
                    and not q_st.lower().startswith("__action:")
                ):
                    session.zone0_phase = "prereq"
                    await session.save()
                    session_reload = await self.session_repository.get_by_id(session_id)
                    if session_reload is None:
                        raise ValueError("Session not found")
                    return await zone0_emit_prereq_or_skip(
                        _z0_ctx,
                        session_reload,
                        session_id,
                        student_id,
                        topic,
                        post_anchor_reply=q_st or None,
                    )
                if q_st.lower().startswith("__action:"):
                    return {"type": "noop"}
                return {"type": "noop"}
            return await zone0_idle_dispatch(
                _z0_ctx, session, session_id, student_id, topic, _z0_phase
            )
        # ── End Zone 0 intercept ─────────────────────────────────────────────

        # Strict cluster boundary: quiz can only run when the current concept is
        # the last concept inside its cluster.
        if action == "quiz":
            kc = [
                str(c).strip()
                for c in (getattr(session, "key_concepts", None) or [])
                if str(c).strip()
            ]
            idx = int(getattr(session, "current_concept_index", 0) or 0)
            clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
            if not flat_index_is_last_in_its_cluster(idx, clusters):
                return {"type": "noop"}

        if flow == "idle":
            if action == "skip":
                return await self._teacher_advance_skip(session, session_id, student_id, topic)
            _cz_idle = getattr(session, "current_zone", None)
            _z_idle = int(_cz_idle) if _cz_idle is not None else 0
            if _z_idle >= 3:
                from app.services.progression.zone_transition_coordinator import (
                    ZoneTransitionCoordinator,
                )

                coordinator = ZoneTransitionCoordinator()
                coordinator.enter_zone_entry_stub(session, _z_idle)
                await session.save()
                return ZoneTransitionCoordinator.zone_entry_payload(_z_idle)
            _ph_idle = str(getattr(session, "zone0_phase", "done") or "done")
            if _z_idle == 0 and _ph_idle != "done":
                # Zone 0 still active but message was not handled above — do not
                # fall through to Zone 1 micro-teach / RAG.
                return {"type": "noop"}
            # ── Auto-explain: no "Start" button, no waiting ──────────────────────
            # Any input when idle (including the bootstrap ".") immediately triggers
            # an explanation for the current concept.  Flow transitions to "explaining"
            # so the frontend knows to request the quiz once streaming is done.
            from app.services.pedagogy import vtse_opening_claim as _vtse_claim

            if _vtse_claim.is_opening_in_progress(session) or str(
                getattr(session, "flow_state", "") or ""
            ) == _vtse_claim.FLOW_VTSE_OPENING:
                return _vtse_claim.acknowledge_existing_opening(session)
            if _vtse_claim.is_opening_ready(session) and should_run_micro_teaching(
                session, ignore_opening_claim=True
            ):
                # Opening already delivered for this concept — never regenerate.
                return _vtse_claim.acknowledge_existing_opening(session)

            prev_cc = (session.current_concept or "").strip().lower()
            _cc_raw = self._get_current_concept(session, topic) or ""
            session.current_concept = _cc_raw[:500] if _cc_raw else None
            if prev_cc and (session.current_concept or "").strip().lower() != prev_cc:
                session.current_step_in_concept = 0
                session.current_question = None
                session.cluster_check_pending = False
                session.cluster_check_concepts = None
            cc = session.current_concept or ""
            rag_q = (
                f'Please explain the concept "{cc}" clearly with a simple definition, '
                "example, and short summary."
            )
            _ctx = self._build_handler_context()
            if should_run_micro_teaching(session):
                from app.services.pedagogy.concept_teaching_orchestrator import (
                    ConceptTeachingOrchestrator,
                )

                _cto_open = ConceptTeachingOrchestrator()
                await _cto_open.ensure_sequence_snapshot(session)
                _c_idx = _vtse_claim.concept_index(session)
                _claimed = await _vtse_claim.atomic_claim_vtse_opening(
                    session_id,
                    concept_index=_c_idx,
                    set_flow_opening=True,
                )
                if _claimed is None:
                    return _vtse_claim.acknowledge_existing_opening(session)
                _vtse_claim.hydrate_opening_fields(
                    session,
                    {
                        "concept_vtse_opening_status": _vtse_claim.VTSE_OPENING_STARTING,
                        "concept_vtse_opening_for_index": _c_idx,
                        "flow_state": _vtse_claim.FLOW_VTSE_OPENING,
                    },
                )
                try:
                    body = await teacher_micro_teaching_opening(
                        _ctx, session, session_id, student_id, topic
                    )
                except Exception:  # noqa: BLE001
                    await _vtse_claim.atomic_mark_vtse_opening_failed(
                        session_id, concept_index=_c_idx
                    )
                    raise
                await _vtse_claim.atomic_mark_vtse_opening_ready(
                    session_id, concept_index=_c_idx
                )
                session.concept_vtse_opening_status = _vtse_claim.VTSE_OPENING_READY
                if isinstance(body, dict):
                    if str(body.get("type") or "") == "vtse_opening_ack":
                        return body
                    # Forward ALL fields from micro-opening (preserves instruction_timeline_v3,
                    # planner_source, timeline_metadata, etc.)
                    _micro_out = {
                        "type": "explanation",
                        "current_concept": cc,
                        **body,
                    }
                    import logging as _lg
                    _lg.getLogger(__name__).info(
                        "[VTSE_ZONE1] SESSION_FORWARDING_TIMELINE itv3_present=%s planner_source=%s",
                        "instruction_timeline_v3" in _micro_out,
                        _micro_out.get("planner_source", "none"),
                    )
                    return _micro_out
                return {
                    "type": "explanation",
                    "message": str(body).strip(),
                    "current_concept": cc,
                }
            body = await self._teacher_explain_turn(
                session,
                session_id,
                student_id,
                topic,
                rag_q,
                intent="EXPLAIN",
                state_at_entry="explaining",
                next_flow_state="explaining",
                next_learning_state="explaining",
            )
            if body is None:
                # Advance flow_state so this path is never re-entered on the
                # next frontend call (prevents the infinite "idle" loop).
                session = await self.session_repository.get_by_id(session_id)
                if session is not None:
                    session.flow_state = "explaining"
                    await session.save()
                return {
                    "type": "explanation",
                    "message": (
                        f'Let me tell you about "{cc}". '
                        "This concept doesn't have detailed notes yet, "
                        "but I'll do my best to explain it clearly."
                    ),
                    "current_concept": cc,
                }
            if isinstance(body, dict):
                return body
            session = await self.session_repository.get_by_id(session_id)
            return {
                "type": "explanation",
                "message": str(body).strip(),
                "current_concept": cc,
            }

        # ── flow == "quizzing" ──────────────────────────────────────────────────
        # A quiz is already live and the system is waiting for the student's real
        # typed/spoken answer.  Any system action that arrives here (e.g. a
        # spurious "__action:quiz" re-trigger from the frontend) must NOT be
        # evaluated as a quiz answer.  Re-emit the current question so the student
        # sees it again, or silently absorb it.
        if flow == "quizzing":
            if action is not None:
                # System / action message — ignore; re-surface the waiting question.
                q_text = getattr(session, "current_question", None) or ""
                cc = getattr(session, "current_concept", None) or ""
                if q_text:
                    return {
                        "type": "quiz",
                        "message": "",
                        "question": str(q_text),
                        "current_concept": cc,
                    }
            # Real student answer → return None so _answer_tutor_question_inner
            # evaluates it through the normal quiz-answer path.
            return None

        # ── flow == "explaining" ─────────────────────────────────────────────────
        # The frontend sends a follow-up call once explanation streaming + TTS has
        # finished.  This state's sole purpose is to emit the quiz.
        if flow == "explaining":
            if action == "skip":
                return await self._teacher_advance_skip(session, session_id, student_id, topic)
            if action == "ask_question":
                return {
                    "type": "explanation",
                    "message": (
                        "I'll explain step by step, and I'll give you time to ask "
                        "questions shortly."
                    ),
                    "current_concept": session.current_concept or "",
                }
            # ── Zone 1 structured concept questions (post-VTSE; not flow checkpoints) ──
            if is_concept_questions_mode(session) or getattr(session, "flow_state", "") == "concept_questions":
                if action == "quiz":
                    return {"type": "noop"}
                _ctx = self._build_handler_context()
                return await handle_concept_questions_dispatch(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    student_text=(question or "").strip(),
                    action=action,
                )
            if is_cluster_quiz_mode(session) or getattr(session, "flow_state", "") == "cluster_quiz":
                if action == "quiz":
                    return {"type": "noop"}
                cluster_action = normalize_cluster_quiz_action(
                    session,
                    action=action,
                    student_text=(question or ""),
                )
                _ctx = self._build_handler_context()
                return await handle_cluster_quiz_dispatch(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    student_text=(question or "").strip(),
                    action=cluster_action,
                )
            # ── PRIORITY 1: micro-teaching reply (runs before question-interrupt check).
            # Student answers MUST go through evaluation even when the text looks like
            # a question (contains "?", starts with "does/is/how/etc.").
            if (
                question.strip()
                and not question.strip().lower().startswith("__action:")
                and (getattr(session, "current_question", None) or "").strip()
                and int(getattr(session, "current_step_in_concept", 0) or 0)
                < MICRO_TEACH_STEP_READY_QUIZ
                and action not in ("skip", "ask_question", "explain_again", "quiz")
            ):
                _ctx = self._build_handler_context()
                msg = await teacher_micro_teaching_process_reply(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    question.strip(),
                )
                if isinstance(msg, dict):
                    msg_text = str(msg.get("message", "")).strip()
                    visual = msg.get("visual")
                else:
                    msg_text = str(msg).strip()
                    visual = None
                session = await self.session_repository.get_by_id(session_id)
                cc_out = getattr(session, "current_concept", None) or ""
                # Fix 4 — Interactive Q&A entry:
                # When micro-teaching completes and Q&A is triggered, return a structured
                # question_prompt with action buttons so the student can choose interactively.
                if (
                    getattr(session, "flow_state", "") == "waiting_for_question"
                    and bool(getattr(session, "student_questions_active", False))
                ):
                    return {
                        "type": "question_prompt",
                        "message": msg_text,
                        "current_concept": cc_out,
                        "buttons": teacher_buttons(
                            [
                                ("ask_another", "Yes, I have a question"),
                                ("understand", "No, continue"),
                            ]
                        ),
                        "visual": visual,
                    }
                return {
                    "type": "explanation",
                    "message": msg_text,
                    "current_concept": cc_out,
                    "visual": visual,
                }
            # ── PRIORITY 2: mid-teaching question interrupt.
            # Only fires when there is NO active micro-question pending.
            # Guard prevents stealing answers that look like questions.
            _has_pending_micro_q = (
                (getattr(session, "current_question", None) or "").strip()
                and int(getattr(session, "current_step_in_concept", 0) or 0)
                < MICRO_TEACH_STEP_READY_QUIZ
            )
            if (
                action is None
                and self._looks_like_question_interrupt(question)
                and not question.strip().lower().startswith("__action:")
                and topic is not None
                and not _has_pending_micro_q
            ):
                # Pause VTSE / Zone-1 board — do NOT complete the stage or arm
                # Concept Check. Resume marker stays concept_teaching_await_vtse_done.
                _await_vtse = bool(
                    getattr(session, "concept_teaching_await_vtse_done", False)
                )
                cc = session.current_concept or self._get_current_concept(session, topic) or ""
                rag_q = (
                    f'The student asked during teaching: "{question.strip()}". '
                    "Answer clearly in 1-2 sentences, then add one short line returning "
                    f'to the current concept "{cc}" with a bridge such as '
                    '"Let’s bring this back to what we were exploring..." '
                    "or equivalent natural phrasing."
                )
                body = await self._teacher_explain_turn(
                    session,
                    session_id,
                    student_id,
                    topic,
                    rag_q,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="explaining",
                    next_learning_state="explaining",
                )
                session = await self.session_repository.get_by_id(session_id)
                if session is not None and _await_vtse:
                    # Explain-turn must not clear the resume marker or invent a
                    # second VTSE timeline that would look like stage completion.
                    session.concept_teaching_await_vtse_done = True
                    session.concept_questions_active = False
                    fields: dict = {
                        "concept_teaching_await_vtse_done": True,
                        "concept_questions_active": False,
                    }
                    if getattr(session, "flow_state", "") == "concept_questions":
                        session.flow_state = "explaining"
                        fields["flow_state"] = "explaining"
                    from datetime import datetime

                    try:
                        await Session.get_pymongo_collection().update_one(
                            {"_id": session_id},
                            {"$set": {**fields, "updated_at": datetime.utcnow()}},
                        )
                    except Exception:
                        logger.exception(
                            "[VTSE_STAGE] interrupt_marker_narrow_failed session_id=%s",
                            session_id,
                        )
                        await session.save()
                if body is None:
                    return {
                        "type": "explanation",
                        "message": (
                            "Good question. Briefly: it links to the key idea we are building. "
                            "Let’s bring this back to what we were exploring and keep going."
                        ),
                        "current_concept": cc,
                        "vtse_question_interrupt": 1 if _await_vtse else 0,
                    }
                if isinstance(body, dict):
                    out = dict(body)
                    # Interrupt answers are conversational — never board-owned VTSE.
                    out.pop("instruction_timeline_v3", None)
                    out.pop("planner_source", None)
                    out.pop("timeline_metadata", None)
                    if _await_vtse:
                        out["vtse_question_interrupt"] = 1
                        out["concept_teaching_await_vtse_done"] = 1
                    return out
                return {
                    "type": "explanation",
                    "message": str(body).strip(),
                    "current_concept": cc,
                    "vtse_question_interrupt": 1 if _await_vtse else 0,
                    **(
                        {"concept_teaching_await_vtse_done": 1}
                        if _await_vtse
                        else {}
                    ),
                }
            # Auto-quiz before micro answers: prompt student to reply in chat
            if (
                action == "quiz"
                and (getattr(session, "current_question", None) or "").strip()
                and int(getattr(session, "current_step_in_concept", 0) or 0)
                < MICRO_TEACH_STEP_READY_QUIZ
            ):
                cc_out = getattr(session, "current_concept", None) or ""
                return {
                    "type": "explanation",
                    "message": (
                        "Pause for a moment—when you have a thought, type it in the chat "
                        "and we'll build from there."
                    ),
                    "current_concept": cc_out,
                }
            if action == "explain_again":
                cc = session.current_concept or self._get_current_concept(session, topic) or ""
                cc = str(cc)[:500]
                session.current_concept = cc or session.current_concept
                # Do NOT reset current_step_in_concept — stay at the same point in the
                # micro-teaching loop. Only clear the pending question so the student
                # can respond freely after the clarification. No concept restart.
                session.current_question = None
                await session.save()
                # Re-explain the current idea in simpler terms with a different example.
                # This is a clarification turn, not a restart of the concept from scratch.
                rag_q = (
                    f'The student asked to re-explain the current idea for concept "{cc}". '
                    "Rephrase the same idea more simply using a different concrete example. "
                    "Do NOT restart from the beginning of the concept. "
                    "Continue from where the teaching was. "
                    "End with one easy check-in question about that same idea."
                )
                body = await self._teacher_explain_turn(
                    session,
                    session_id,
                    student_id,
                    topic,
                    rag_q,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="explaining",
                    next_learning_state="explaining",
                )
                if body is None:
                    session = await self.session_repository.get_by_id(session_id)
                    if session is not None:
                        session.flow_state = "explaining"
                        await session.save()
                    return {
                        "type": "explanation",
                        "message": f'Let me try explaining this differently for "{cc}".',
                        "current_concept": cc,
                    }
                if isinstance(body, dict):
                    return body
                session = await self.session_repository.get_by_id(session_id)
                return {
                    "type": "explanation",
                    "message": str(body).strip(),
                    "current_concept": cc,
                }
            # Default: only cluster-final concepts trigger a quiz via __action:quiz.
            # Per-concept quizzes are not allowed in Zone 1 — Q&A handles the
            # transition. Any other input here is a no-op.
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")
            if action == "quiz":
                return await self._generate_and_return_cluster_quiz(
                    session, session_id, student_id
                )
            # Routing fallback: if a micro-question is still pending, always evaluate
            # the student's reply through micro-teaching instead of dropping to noop.
            if (
                question.strip()
                and not question.strip().lower().startswith("__action:")
                and (getattr(session, "current_question", None) or "").strip()
                and int(getattr(session, "current_step_in_concept", 0) or 0)
                < MICRO_TEACH_STEP_READY_QUIZ
            ):
                _ctx = self._build_handler_context()
                msg = await teacher_micro_teaching_process_reply(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    question.strip(),
                )
                if isinstance(msg, dict):
                    msg_text = str(msg.get("message", "")).strip()
                    visual = msg.get("visual")
                else:
                    msg_text = str(msg).strip()
                    visual = None
                session = await self.session_repository.get_by_id(session_id)
                cc_out = getattr(session, "current_concept", None) or ""
                return {
                    "type": "explanation",
                    "message": msg_text,
                    "current_concept": cc_out,
                    "visual": visual,
                }
            # Zone 1 safety fallback: if user sent valid text but current_question
            # is unexpectedly empty, still process through micro-teaching reply.
            _z_fb = int(getattr(session, "current_zone", 1) or 1)
            if (
                _z_fb == 1
                and action is None
                and question.strip()
                and not question.strip().lower().startswith("__action:")
                and not (getattr(session, "current_question", None) or "").strip()
            ):
                _ctx = self._build_handler_context()
                msg = await teacher_micro_teaching_process_reply(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    question.strip(),
                )
                if isinstance(msg, dict):
                    msg_text = str(msg.get("message", "")).strip()
                    visual = msg.get("visual")
                else:
                    msg_text = str(msg).strip()
                    visual = None
                session = await self.session_repository.get_by_id(session_id)
                cc_out = getattr(session, "current_concept", None) or ""
                if (
                    getattr(session, "flow_state", "") == "waiting_for_question"
                    and bool(getattr(session, "student_questions_active", False))
                ):
                    return {
                        "type": "question_prompt",
                        "message": msg_text,
                        "current_concept": cc_out,
                        "buttons": teacher_buttons(
                            [
                                ("ask_another", "Yes, I have a question"),
                                ("understand", "No, continue"),
                            ]
                        ),
                        "visual": visual,
                    }
                return {
                    "type": "explanation",
                    "message": msg_text,
                    "current_concept": cc_out,
                    "visual": visual,
                }
            # Not a quiz action and micro-teaching already closed — do nothing.
            return {"type": "noop"}

        if flow == "checking_understanding":
            # Legacy compatibility: this state is kept for sessions that were
            # already in-flight before the "explaining" state was introduced.
            # New sessions will use flow=="explaining" instead.
            if action == "skip":
                return await self._teacher_advance_skip(session, session_id, student_id, topic)
            if action == "ask_question":
                return {
                    "type": "explanation",
                    "message": (
                        "I'll explain step by step, and I'll give you time to ask "
                        "questions shortly."
                    ),
                    "current_concept": session.current_concept or "",
                }
            if action == "explain_again":
                cc = session.current_concept or self._get_current_concept(session, topic) or ""
                cc = str(cc)[:500]
                session.current_concept = cc or session.current_concept
                rag_q = (
                    f'Please explain the concept "{cc}" again, step by step, '
                    "with a fresh example."
                )
                body = await self._teacher_explain_turn(
                    session,
                    session_id,
                    student_id,
                    topic,
                    rag_q,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="explaining",
                    next_learning_state="explaining",
                )
                if body is None:
                    return {
                        "type": "explanation",
                        "message": "I don't have enough information on this topic yet.",
                        "current_concept": cc,
                    }
                if isinstance(body, dict):
                    return body
                session = await self.session_repository.get_by_id(session_id)
                return {
                    "type": "explanation",
                    "message": str(body).strip(),
                    "current_concept": cc,
                }
            # Legacy routing fallback: evaluate any pending concept-check reply.
            if (
                question.strip()
                and not question.strip().lower().startswith("__action:")
                and (getattr(session, "current_question", None) or "").strip()
                and int(getattr(session, "current_step_in_concept", 0) or 0)
                < MICRO_TEACH_STEP_READY_QUIZ
            ):
                _ctx = self._build_handler_context()
                msg = await teacher_micro_teaching_process_reply(
                    _ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    question.strip(),
                )
                if isinstance(msg, dict):
                    msg_text = str(msg.get("message", "")).strip()
                    visual = msg.get("visual")
                else:
                    msg_text = str(msg).strip()
                    visual = None
                session = await self.session_repository.get_by_id(session_id)
                cc_out = getattr(session, "current_concept", None) or ""
                return {
                    "type": "explanation",
                    "message": msg_text,
                    "current_concept": cc_out,
                    "visual": visual,
                }
            # "understand", "quiz" intent, any unrecognised input → generate quiz
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")
            if action == "quiz":
                return await self._generate_and_return_cluster_quiz(
                    session, session_id, student_id
                )
            return await self._generate_and_return_quiz(session, session_id, student_id)

        if flow == "waiting_for_question":
            if action == "skip":
                return await self._teacher_advance_skip(session, session_id, student_id, topic)
            if action == "understand":
                if bool(getattr(session, "student_questions_active", False)):
                    # Q&A complete — determine whether cluster quiz or next concept follows.
                    _kc_qa = [
                        str(c).strip()
                        for c in (getattr(session, "key_concepts", None) or [])
                        if str(c).strip()
                    ]
                    _idx_qa = int(getattr(session, "current_concept_index", 0) or 0)
                    _clusters_qa = resolve_clusters(
                        _kc_qa, getattr(session, "concept_clusters", None)
                    )
                    _at_cluster_end = flat_index_is_last_in_its_cluster(_idx_qa, _clusters_qa)
                    session.student_questions_active = False
                    session.student_questions_concept = None
                    session.current_mode = "normal"
                    session.learning_state = "explaining"
                    if _at_cluster_end:
                        # Cluster quiz next — step already at MICRO_TEACH_STEP_READY_QUIZ.
                        # Setting flow="explaining" lets the frontend auto-trigger __action:quiz.
                        session.flow_state = "explaining"
                        await session.save()
                        return {
                            "type": "explanation",
                            "message": "Great! Let's put these ideas together.",
                            "current_concept": session.current_concept or "",
                        }
                    else:
                        # Advance to next concept; micro-teaching will start on next idle turn.
                        from app.services.session_concept_tracking import (
                            sync_session_concept_fields,
                        )

                        sync_session_concept_fields(session, index=_idx_qa + 1)
                        session.current_step_in_concept = 0
                        session.micro_last_connection_round = -1
                        session.current_question = None
                        session.current_zone = 1
                        session.flow_state = "idle"
                        await session.save()
                        return {
                            "type": "explanation",
                            "message": "Perfect — let's keep going.",
                            "current_concept": session.current_concept or "",
                        }
                # Student finished asking their question; move back to explaining
                # so the frontend will auto-trigger the quiz on the next call.
                session.flow_state = "explaining"
                session.learning_state = "explaining"
                await session.save()
                return {
                    "type": "understanding_check",
                    "message": "Do you understand or do you have a question?",
                    "current_concept": session.current_concept or "",
                    "buttons": teacher_buttons(
                        [
                            ("understand", "I understand"),
                            ("ask_question", "I have a question"),
                            ("skip", "Skip"),
                        ]
                    ),
                }
            if action == "explain_again":
                cc = session.current_concept or self._get_current_concept(session, topic) or ""
                cc = str(cc)[:500]
                rag_q = (
                    f'Please explain the concept "{cc}" again, step by step, with a fresh example.'
                )
                body = await self._teacher_explain_turn(
                    session,
                    session_id,
                    student_id,
                    topic,
                    rag_q,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="waiting_for_question",
                    next_learning_state=None,
                )
                if body is None:
                    return {
                        "type": "explanation",
                        "message": "I don't have enough information on this topic yet.",
                    }
                return {
                    "type": "question_answered",
                    "message": body.strip(),
                    "buttons": teacher_buttons(
                        [
                            ("understand", "I understand"),
                            ("ask_another", "Ask another"),
                            ("explain_again", "Explain again"),
                            ("skip", "Skip"),
                        ]
                    ),
                }
            if action == "ask_another":
                if bool(getattr(session, "student_questions_active", False)):
                    c = (getattr(session, "student_questions_concept", None) or "this concept").strip()
                    return {
                        "type": "question_prompt",
                        "message": f"Of course! What would you like to know about **{c}**?",
                    }
                return {
                    "type": "question_prompt",
                    "message": "Sure! What would you like to know?",
                }
            if action is None:
                if bool(getattr(session, "student_questions_active", False)) and self._is_no_more_questions_text(question):
                    # Q&A complete — same cluster-boundary routing as the "understand" path.
                    _kc_nmq = [
                        str(c).strip()
                        for c in (getattr(session, "key_concepts", None) or [])
                        if str(c).strip()
                    ]
                    _idx_nmq = int(getattr(session, "current_concept_index", 0) or 0)
                    _clusters_nmq = resolve_clusters(
                        _kc_nmq, getattr(session, "concept_clusters", None)
                    )
                    _at_cluster_end_nmq = flat_index_is_last_in_its_cluster(
                        _idx_nmq, _clusters_nmq
                    )
                    session.student_questions_active = False
                    session.student_questions_concept = None
                    session.current_mode = "normal"
                    session.learning_state = "explaining"
                    if _at_cluster_end_nmq:
                        session.flow_state = "explaining"
                        await session.save()
                        return {
                            "type": "explanation",
                            "message": "Great! Let's put these ideas together.",
                            "current_concept": session.current_concept or "",
                        }
                    else:
                        from app.services.session_concept_tracking import (
                            sync_session_concept_fields,
                        )

                        sync_session_concept_fields(session, index=_idx_nmq + 1)
                        session.current_step_in_concept = 0
                        session.micro_last_connection_round = -1
                        session.current_question = None
                        session.current_zone = 1
                        session.flow_state = "idle"
                        await session.save()
                        return {
                            "type": "explanation",
                            "message": "Perfect — let's keep going.",
                            "current_concept": session.current_concept or "",
                        }
                topic_note_repository = TopicNoteRepository()
                video_subtitle_repository = VideoSubtitleRepository()
                topic_question_repository = TopicQuestionRepository()
                rag_service = RAGService(
                    topic_note_repository,
                    video_subtitle_repository,
                    topic_question_repository,
                    self.topic_repository,
                )
                event_repository = EventRepository()
                await event_repository.create(
                    {
                        "organization_id": session.organization_id,
                        "session_id": session_id,
                        "student_id": student_id,
                        "event_type": SessionEventType.QUESTION,
                        "content": question[:4000] if len(question) > 4000 else question,
                        "timestamp": datetime.utcnow(),
                    }
                )
                student_profile = await StudentProfile.find_one(
                    {
                        "organization_id": session.organization_id,
                        "user_id": session.student_id,
                    }
                )
                teaching_style = (
                    student_profile.preferred_teaching_style
                    if student_profile is not None
                    else None
                )
                interests = (
                    student_profile.interests if student_profile is not None else []
                )
                interest_category = interests[0] if interests else "general"
                difficulty_level = (
                    student_profile.preferred_depth
                    if student_profile is not None
                    else None
                )
                topic_id = session.topic_id
                q_concept = getattr(session, "current_concept", None)
                if bool(getattr(session, "student_questions_active", False)):
                    q_concept = getattr(session, "student_questions_concept", None) or q_concept
                notes = await rag_service.get_topic_notes(
                    topic_id=topic_id,
                    organization_id=session.organization_id,
                    teaching_style=teaching_style,
                    interest_category=interest_category,
                    difficulty_level=difficulty_level,
                    current_concept=q_concept,
                    user_query=question,
                    curriculum_class_id=getattr(session, "curriculum_class_id", None),
                    curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
                )
                context = await rag_service.build_context(
                    notes,
                    topic_id=topic_id,
                    organization_id=session.organization_id,
                    curriculum_class_id=getattr(session, "curriculum_class_id", None),
                    curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
                )
                topic_for_prompt = await self._get_topic_or_teacher_topic(topic_id)
                body = await self._generate_tutor_rag_reply(
                    session,
                    session_id,
                    student_id,
                    question,
                    topic_id,
                    "UNKNOWN",
                    "explaining",
                    topic_for_prompt,
                    rag_service,
                    context,
                    student_profile,
                    event_repository,
                )
                session = await self.session_repository.get_by_id(session_id)
                if session is not None:
                    session.flow_state = "waiting_for_question"
                    await session.save()
                if bool(getattr(session, "student_questions_active", False)):
                    return {
                        "type": "question_answered",
                        "message": (
                            body.strip()
                            + "\n\nAny other questions about this concept?"
                        ),
                        "buttons": teacher_buttons(
                            [
                                ("ask_another", "Ask another"),
                                ("understand", "No, continue"),
                            ]
                        ),
                    }
                return {
                    "type": "question_answered",
                    "message": body.strip(),
                    "buttons": teacher_buttons(
                        [
                            ("understand", "I understand"),
                            ("ask_another", "Ask another"),
                            ("explain_again", "Explain again"),
                            ("skip", "Skip"),
                        ]
                    ),
                }

        return None

    @staticmethod
    def _is_persistable_user_chat_message(question: str) -> bool:
        q = (question or "").strip()
        if not q or q == ".":
            return False
        if q.lower().startswith("__action:"):
            return False
        return True

    def _assistant_message_payload(
        self, result: str | dict
    ) -> tuple[str, str | None, str | None]:
        """Returns (content, message_type, metadata_json) for chat persistence."""
        meta_out: str | None = None
        if isinstance(result, dict):
            t_raw = str(result.get("type") or "").strip()
            t = t_raw or None
            extra: dict[str, Any] = {}
            buttons = result.get("buttons")
            if buttons:
                extra["buttons"] = buttons
            if result.get("type") == "feedback":
                extra["correct"] = bool(result.get("correct"))
            if extra:
                try:
                    meta_out = json.dumps(extra)[:8000]
                except (TypeError, ValueError):
                    meta_out = None
            if result.get("type") == "quiz":
                intro = str(result.get("message") or "").strip()
                qtext = str(result.get("question") or "").strip()
                parts: list[str] = []
                if intro:
                    parts.append(intro)
                if qtext:
                    parts.append(f"Question: {qtext}")
                content = "\n\n".join(parts) if parts else (qtext or intro)
                return (content, t or "quiz", meta_out)
            if result.get("message") is not None:
                body = str(result.get("message") or "").strip()
                if body:
                    return (body, t, meta_out)
            if result.get("answer") is not None:
                return (
                    str(result.get("answer") or "").strip(),
                    t or "explanation",
                    meta_out,
                )
            return (str(result), t, meta_out)
        text = str(result).strip()
        return (text, "explanation", None)

    async def _persist_chat_user(
        self, session_id: PydanticObjectId, content: str
    ) -> None:
        if self._message_repository is None:
            return
        try:
            await self._message_repository.create_message(
                session_id=session_id,
                role="user",
                content=content[:120_000],
                message_type=None,
            )
        except Exception:
            logger.exception("Failed to persist user chat message")

    @staticmethod
    def _should_skip_assistant_chat_persist(result: str | dict) -> bool:
        if not isinstance(result, dict):
            return False
        t = str(result.get("type") or "").strip().lower()
        return t in (
            "noop",
            "visual_teaching_sentence_ack",
            "visual_teaching_advance_ack",
            "vtse_opening_ack",
            "flow_checkpoint_clarification",
            "concept_notes",
            "zone0_anchor",
            "zone0_curiosity",
            "zone0_mirror",
            "zone0_prereq",
            "session_intro_card",
            "cluster_intro_card",
            "session_recall_prompt",
            "session_recall_feedback",
            "cluster_curiosity_prompt",
            "cluster_curiosity_feedback",
        )

    async def _persist_board_turn(
        self,
        session_id: PydanticObjectId,
        session: Session,
        result: str | dict,
    ) -> None:
        if self._board_turn_repository is None or not isinstance(result, dict):
            return
        response_type = str(result.get("type") or "").strip() or None
        timeline = result.get("instruction_timeline_v3")
        has_timeline = isinstance(timeline, dict) and bool(timeline)
        content = ""
        if result.get("message") is not None:
            content = str(result.get("message") or "").strip()
        elif result.get("answer") is not None:
            content = str(result.get("answer") or "").strip()
        tm = result.get("timeline_metadata")
        timeline_metadata = tm if isinstance(tm, dict) else None
        visual = result.get("visual")
        visual_dict = visual if isinstance(visual, dict) else None
        # Zone 0 dual-channel (and similar): merge top-level writing fields into visual
        # so board restore can reveal notes vs speech correctly.
        wm = result.get("writing_mode")
        dt = result.get("display_text")
        writes = result.get("writes")
        if wm is not None or dt is not None or writes is not None:
            merged = dict(visual_dict or {})
            if wm is not None:
                merged["writing_mode"] = str(wm).strip() or None
            if dt is not None:
                merged["display_text"] = str(dt)
            if isinstance(writes, list):
                merged["writes"] = writes
            if not merged.get("type"):
                merged["type"] = "zone0_display"
            visual_dict = merged
        ps = result.get("planner_source")
        planner_source = str(ps).strip() if ps is not None else None
        zone = int(getattr(session, "current_zone", 0) or 0)
        cluster_index = int(getattr(session, "current_cluster_index", 0) or 0)
        concept_index = int(getattr(session, "current_concept_index", 0) or 0)
        concept_id = (
            str(getattr(session, "current_concept", "") or "").strip() or None
        )
        board_prose_types = {
            "zone0_anchor",
            "zone0_curiosity",
            "zone0_mirror",
            "zone0_prereq",
            "session_intro_card",
            "cluster_intro_card",
            "session_recall_prompt",
            "session_recall_feedback",
            "cluster_curiosity_prompt",
            "cluster_curiosity_feedback",
        }
        try:
            if has_timeline:
                await self._board_turn_repository.upsert_timeline_turn(
                    session_id,
                    content=content,
                    instruction_timeline_v3=timeline,
                    timeline_metadata=timeline_metadata,
                    planner_source=planner_source or None,
                    visual=visual_dict,
                    zone=zone,
                    cluster_index=cluster_index,
                    concept_index=concept_index,
                    concept_id=concept_id,
                    response_type=response_type,
                )
            elif response_type in board_prose_types and (content or visual_dict):
                turn_index = await self._board_turn_repository.next_turn_index(
                    session_id
                )
                await self._board_turn_repository.create_turn(
                    session_id,
                    turn_index=turn_index,
                    content=content,
                    visual=visual_dict,
                    zone=zone,
                    cluster_index=cluster_index,
                    concept_index=concept_index,
                    concept_id=concept_id,
                    response_type=response_type,
                )
        except Exception:
            logger.exception("Failed to persist board turn for session_id=%s", session_id)

    async def _persist_board_turn_if_timeline(
        self,
        session_id: PydanticObjectId,
        session: Session,
        result: str | dict,
    ) -> None:
        await self._persist_board_turn(session_id, session, result)

    async def _persist_chat_assistant(
        self, session_id: PydanticObjectId, result: str | dict
    ) -> None:
        if self._should_skip_assistant_chat_persist(result):
            return
        if self._message_repository is None:
            return
        content, mt, meta = self._assistant_message_payload(result)
        content = (content or "").strip()
        if not content:
            return
        try:
            await self._message_repository.create_message(
                session_id=session_id,
                role="assistant",
                content=content[:120_000],
                message_type=mt,
                metadata_json=meta,
            )
        except Exception:
            logger.exception("Failed to persist assistant chat message")

    async def get_chat_messages(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        *,
        limit: int = 200,
    ) -> List[dict[str, Any]]:
        """Return persisted chat history for the session (student must own session)."""
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if self._message_repository is None:
            return []
        rows = await self._message_repository.get_messages(session_id, limit=limit)
        return [
            {
                "role": r.role,
                "content": r.content,
                "message_type": r.message_type,
                "created_at": r.created_at,
                "metadata_json": r.metadata_json,
            }
            for r in rows
        ]

    @staticmethod
    def _board_turn_dict_from_doc(t: Any) -> dict[str, Any]:
        return {
            "turn_index": t.turn_index,
            "content": t.content,
            "instruction_timeline_v3": t.instruction_timeline_v3,
            "timeline_metadata": t.timeline_metadata,
            "planner_source": t.planner_source,
            "visual": t.visual,
            "zone": t.zone,
            "cluster_index": t.cluster_index,
            "concept_index": t.concept_index,
            "concept_id": t.concept_id,
            "response_type": getattr(t, "response_type", None),
            "created_at": t.created_at,
        }

    @staticmethod
    def _supplement_board_turns_from_messages(
        messages: list[dict[str, Any]],
        board_turns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reconstruct Zone 0 / prose board segments missing from board_turns."""
        prose_types = {
            "zone0_anchor",
            "zone0_curiosity",
            "zone0_mirror",
            "zone0_prereq",
            "session_intro_card",
            "cluster_intro_card",
            "session_recall_prompt",
            "session_recall_feedback",
            "cluster_curiosity_prompt",
            "cluster_curiosity_feedback",
        }
        existing_keys: set[str] = set()
        for turn in board_turns:
            key = (turn.get("content") or "").strip().lower()
            if key:
                existing_keys.add(key)
            rt = str(turn.get("response_type") or "").strip()
            if rt in prose_types:
                existing_keys.add(f"type:{rt}:{key[:120]}")

        supplements: list[dict[str, Any]] = []
        next_index = -1
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            mt = str(msg.get("message_type") or "").strip()
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if mt not in prose_types:
                continue
            dedupe_key = f"type:{mt}:{content.lower()[:120]}"
            if content.lower() in existing_keys or dedupe_key in existing_keys:
                continue
            created = msg.get("created_at")
            supplements.append(
                {
                    "turn_index": next_index,
                    "content": content,
                    "instruction_timeline_v3": None,
                    "timeline_metadata": None,
                    "planner_source": None,
                    "visual": None,
                    "zone": 0,
                    "cluster_index": 0,
                    "concept_index": 0,
                    "concept_id": None,
                    "response_type": mt,
                    "created_at": created,
                }
            )
            next_index -= 1
            existing_keys.add(content.lower())
            existing_keys.add(dedupe_key)

        if not supplements:
            return board_turns

        merged = supplements + board_turns
        merged.sort(
            key=lambda row: (
                row.get("created_at") or datetime.min,
                int(row.get("turn_index") or 0),
            )
        )
        for i, row in enumerate(merged):
            row["turn_index"] = i
        return merged

    @staticmethod
    def _apply_restore_beat_metadata(
        board_turns: list[dict[str, Any]],
        restore_static_beat: int | None,
    ) -> None:
        if not board_turns:
            return
        last_timeline_idx = None
        for i, turn in enumerate(board_turns):
            if isinstance(turn.get("instruction_timeline_v3"), dict):
                last_timeline_idx = i
        if last_timeline_idx is None:
            return
        for i, turn in enumerate(board_turns):
            meta = dict(turn.get("timeline_metadata") or {})
            if i == last_timeline_idx and restore_static_beat is not None:
                meta["restore_static_through_beat_index"] = restore_static_beat
                meta["resume_playback_from_beat_index"] = restore_static_beat + 1
            elif i < last_timeline_idx and isinstance(
                turn.get("instruction_timeline_v3"), dict
            ):
                beats = (turn.get("instruction_timeline_v3") or {}).get("beats") or []
                if beats:
                    meta["restore_static_through_beat_index"] = len(beats) - 1
            turn["timeline_metadata"] = meta or None

    async def get_session_restore_payload(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        *,
        message_limit: int = 200,
        board_limit: int = 100,
    ) -> dict[str, Any]:
        """Full resume snapshot: chat, board turns, session meta — no re-generation."""
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")

        topic = await self._get_topic_or_teacher_topic(session.topic_id)
        meta = build_teacher_session_meta(session, topic)
        if meta is not None:
            meta["flow_state"] = str(getattr(session, "flow_state", "") or "idle")

        messages = await self.get_chat_messages(
            session_id, student_id, limit=message_limit
        )

        board_turns: list[dict[str, Any]] = []
        if self._board_turn_repository is not None:
            turns = await self._board_turn_repository.get_turns(
                session_id, limit=board_limit
            )
            for t in turns:
                board_turns.append(self._board_turn_dict_from_doc(t))

        board_turns = self._supplement_board_turns_from_messages(
            messages, board_turns
        )

        suppress_concept_q = self._restore_should_suppress_concept_questions(
            session, messages
        )
        if suppress_concept_q and meta is not None:
            meta = {
                **meta,
                "concept_questions_active": False,
                "concept_question_index": 0,
                "concept_question_followup": False,
                "concept_question_clarifying": False,
                "concept_question_pending_advance": False,
                "flow_state": "explaining",
            }
            if int(getattr(session, "current_zone", 0) or 0) >= 1:
                meta["micro_quiz_hold"] = 1

        restore_static_beat = self._restore_static_beat_index(
            session, ignore_concept_questions=suppress_concept_q
        )
        self._apply_restore_beat_metadata(board_turns, restore_static_beat)

        pending_board: dict[str, Any] | None = None
        cache = getattr(session, "zone1_timeline_cache", None)
        if isinstance(cache, dict) and cache:
            cache_concept = str(getattr(session, "zone1_board_concept_id", "") or "").strip()
            last_turn_concept = (
                str(board_turns[-1].get("concept_id") or "").strip()
                if board_turns
                else ""
            )
            last_timeline = (
                board_turns[-1].get("instruction_timeline_v3")
                if board_turns
                else None
            )
            same_timeline = (
                isinstance(last_timeline, dict)
                and last_timeline.get("timeline_id") == cache.get("timeline_id")
            )
            if not same_timeline or cache_concept != last_turn_concept:
                pending_board = {
                    "content": "",
                    "instruction_timeline_v3": cache,
                    "timeline_metadata": {
                        "playback_start_beat_index": 0,
                        "instruction_display_mode": "board_only",
                    },
                    "planner_source": None,
                    "zone": int(getattr(session, "current_zone", 0) or 0),
                    "cluster_index": int(
                        getattr(session, "zone1_board_cluster_index", 0) or 0
                    ),
                    "concept_index": int(
                        getattr(session, "current_concept_index", 0) or 0
                    ),
                    "concept_id": cache_concept or None,
                }
            elif board_turns:
                pending_board = {
                    **board_turns[-1],
                    "instruction_timeline_v3": cache,
                    "is_cache_update": True,
                }
        if pending_board and restore_static_beat is not None:
            pm = dict(pending_board.get("timeline_metadata") or {})
            pm["restore_static_through_beat_index"] = restore_static_beat
            pending_board["timeline_metadata"] = pm

        progression_view = None
        track_key = getattr(session, "progression_track_key", None)
        if track_key:
            from app.services.progression.plan_progress_coordinator import (
                PlanProgressCoordinator,
            )

            coordinator = PlanProgressCoordinator()
            await coordinator.reconcile_progress_on_restore(session)
            progression_view = await coordinator.get_progress_view(
                student_id, track_key
            )

        return {
            "session_id": str(session_id),
            "topic_id": str(session.topic_id),
            "flow_state": str(getattr(session, "flow_state", "") or "idle"),
            "current_concept": getattr(session, "current_concept", None),
            "current_concept_index": getattr(session, "current_concept_index", None),
            "total_concepts": getattr(session, "total_concepts", None),
            "current_zone": getattr(session, "current_zone", None),
            "meta": meta,
            "messages": messages,
            "board_turns": board_turns,
            "pending_board": pending_board,
            "restore_static_beat_index": restore_static_beat,
            "restore_suppress_concept_questions": suppress_concept_q,
            "student_scratchpad_notes": (
                str(getattr(session, "student_scratchpad_notes", "") or "").strip()
                or None
            ),
            "progression": progression_view,
        }

    @staticmethod
    def _restore_should_suppress_concept_questions(
        session: Session,
        messages: list[dict[str, Any]],
    ) -> bool:
        """
        Concept Q can be armed by a spurious auto-quiz while VTSE was still playing.

        If the student never typed a real answer, restore mid-VTSE instead.
        Historical flow_checkpoint_index alone is NOT evidence of an active
        mid-VTSE state — only await_vtse_done / pending checkpoint are.
        """
        if not bool(getattr(session, "concept_questions_active", False)):
            return False
        if int(getattr(session, "concept_question_index", 0) or 0) > 0:
            return False
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = str(msg.get("content") or "").strip()
            if not content or content == ".":
                continue
            if content.lower().startswith("__action:"):
                continue
            return False
        # Legitimate post-VTSE Concept Check — do not suppress.
        if not bool(getattr(session, "concept_teaching_await_vtse_done", False)):
            flow = str(getattr(session, "flow_state", "") or "").strip()
            has_q = bool((getattr(session, "current_question", None) or "").strip())
            if flow == "concept_questions" or has_q:
                return False
        # Still awaiting VTSE board completion, or an open process checkpoint.
        if bool(getattr(session, "concept_teaching_await_vtse_done", False)):
            return True
        if bool(getattr(session, "flow_checkpoint_pending", False)):
            return True
        return False

    @staticmethod
    def _infer_restore_beat_from_flow_checkpoint(session: Session) -> int | None:
        """Match frontend FLOW_CHECKPOINT_INTERVAL (=2) flow-node grouping."""
        fc = int(getattr(session, "flow_checkpoint_index", 0) or 0)
        if fc <= 0:
            return None
        interval = 2
        return max(0, fc * interval - 1)

    @staticmethod
    def _restore_static_beat_index(
        session: Session,
        *,
        ignore_concept_questions: bool = False,
    ) -> int | None:
        """
        Beat index through which VTSE was completed on the client.

        Returns None when the full timeline should be shown (concept Q, notes, etc.).
        """
        if not ignore_concept_questions and bool(
            getattr(session, "concept_questions_active", False)
        ):
            return None
        if bool(getattr(session, "concept_notes_active", False)):
            return None
        step = int(getattr(session, "current_step_in_concept", 0) or 0)
        if step >= MICRO_TEACH_STEP_READY_QUIZ:
            return None
        saved = getattr(session, "zone1_last_completed_beat_index", None)
        if isinstance(saved, int) and saved >= 0:
            return saved
        inferred = SessionService._infer_restore_beat_from_flow_checkpoint(session)
        if inferred is not None:
            return inferred
        return 0

    async def save_board_playback_checkpoint(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        beat_index: int,
        *,
        timeline_id: str | None = None,
    ) -> None:
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        from app.services.pedagogy.vtse_stage_completion import apply_scoped_beat_cursor

        applied = apply_scoped_beat_cursor(
            session,
            beat_index,
            timeline_id=timeline_id,
            allow_final=True,
        )
        if not applied and int(beat_index) >= 0:
            logger.info(
                "[VTSE_STAGE] board_checkpoint_ignored session_id=%s beat=%s timeline_id=%s concept_index=%s",
                session_id,
                beat_index,
                timeline_id,
                getattr(session, "current_concept_index", None),
            )
            try:
                from app.services.pedagogy.teaching_runtime_metrics import incr

                incr("board_checkpoint_ignored")
            except Exception:
                pass
            return
        saved_beat = int(getattr(session, "zone1_last_completed_beat_index", beat_index) or beat_index)
        await Session.get_pymongo_collection().update_one(
            {"_id": session.id},
            {
                "$set": {
                    "zone1_last_completed_beat_index": saved_beat,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        logger.info(
            "[VTSE_STAGE] board_checkpoint_accepted session_id=%s beat=%s timeline_id=%s concept_index=%s",
            session_id,
            saved_beat,
            timeline_id,
            getattr(session, "current_concept_index", None),
        )
        saved_idx = saved_beat
        if self._board_turn_repository is not None and saved_idx >= 0:
            try:
                await self._board_turn_repository.update_last_timeline_metadata(
                    session_id,
                    {
                        "restore_static_through_beat_index": saved_idx,
                        "resume_playback_from_beat_index": saved_idx + 1,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to update board turn checkpoint session_id=%s", session_id
                )

    async def save_student_scratchpad_notes(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        content: str,
    ) -> None:
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        text = (content or "").strip()
        notes = text[:50_000] if text else None
        from datetime import datetime

        await Session.get_pymongo_collection().update_one(
            {"_id": session_id, "student_id": student_id},
            {
                "$set": {
                    "student_scratchpad_notes": notes,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        session.student_scratchpad_notes = notes

    _DIAG_MAX_PREREQ = 3

    async def _diagnostic_teachback_two_recent_wrong(
        self, session_id: PydanticObjectId
    ) -> bool:
        rows = (
            await TeachbackEvaluation.find({"session_id": session_id})
            .sort([("timestamp", -1)])
            .limit(2)
            .to_list()
        )
        if len(rows) < 2:
            return False
        return all(not r.is_correct for r in rows)

    async def _diagnostic_last_teachback_incorrect(
        self, session_id: PydanticObjectId
    ) -> bool:
        rows = (
            await TeachbackEvaluation.find({"session_id": session_id})
            .sort([("timestamp", -1)])
            .limit(1)
            .to_list()
        )
        if not rows:
            return False
        return not bool(rows[0].is_correct)

    @staticmethod
    def _diagnostic_phrase_triggers(user_input_lower: str) -> bool:
        return any(
            n in user_input_lower for n in SessionService._student_struggle_phrases()
        )

    def _diagnostic_should_enter(
        self,
        *,
        user_input_lower: str,
        intent: str,
        is_followup_turn: bool,
        two_quiz_wrong: bool,
    ) -> bool:
        if intent == "EXPLAIN" and is_followup_turn:
            return True
        if self._diagnostic_phrase_triggers(user_input_lower):
            return True
        if two_quiz_wrong:
            return True
        return False

    def _diagnostic_reset_fields(self, session: Session) -> None:
        session.diagnostic_mode = False
        session.diagnostic_step = 0
        session.diagnostic_topic_ids = []
        session.diagnostic_current_index = 0
        session.diagnostic_original_topic_id = None
        session.diagnostic_pending_question = None
        session.diagnostic_resume_question = None
        session.diagnostic_attempt_count = 0

    async def _diagnostic_parse_eval_json(self, raw: str) -> tuple[bool, str]:
        correct = False
        feedback = "Good attempt."
        t = (raw or "").strip()
        if t.startswith("```"):
            rest = t.split("\n", 1)[-1] if "\n" in t else t[3:]
            t = rest.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(t)
            correct = bool(data.get("correct", False))
            fb = data.get("feedback")
            if fb is not None and str(fb).strip():
                feedback = str(fb).strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    data = json.loads(m.group(0))
                    correct = bool(data.get("correct", False))
                    fb = data.get("feedback")
                    if fb is not None and str(fb).strip():
                        feedback = str(fb).strip()
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        return correct, feedback

    async def _diagnostic_llm_evaluate_answer(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        quiz_question: str,
        student_answer: str,
    ) -> tuple[bool, str]:
        topic = await self._get_topic_or_teacher_topic(session.topic_id)
        eval_boundary = self._rag_prompt_boundary_kwargs(session, topic)
        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": student_id}
        )
        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )
        evaluation_prompt = f"""
You are an expert, encouraging tutor evaluating a student's answer.

EVALUATION PHILOSOPHY (follow exactly — this overrides any other instruction):
* Assess UNDERSTANDING, not word-for-word accuracy.
* Mark CORRECT if the student conveys the correct meaning — even in different words, simpler language, or imperfect grammar.
* Mark CORRECT if the student covers the key ideas without using exact technical terms.
* Mark INCORRECT only when the student clearly misunderstands the concept, directly contradicts it, or omits a critical idea entirely.
* Do NOT penalise for synonyms, informal phrasing, or minor detail gaps.
* Do NOT require exact keyword matches.
* When in doubt, lean towards CORRECT if the core idea is present.

Question:
{quiz_question}

Student Answer:
{student_answer.strip()}

Respond ONLY with valid JSON (no extra text, no markdown):
{{"correct": true/false, "feedback": "..."}}

Feedback rules: 1–2 sentences, warm and constructive.
If correct: affirm clearly. If incorrect: name the specific gap and hint at the right direction.
"""
        ctx = f"Topic: {topic.topic_name}" if topic else ""
        ai_response = await rag_service.generate_prompt(
            question=evaluation_prompt,
            context=ctx,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic.topic_name if topic else None,
            learning_state=getattr(session, "learning_state", "explaining"),
            user_intent="EVALUATE",
            last_answer=None,
            is_followup=False,
            current_concept=getattr(session, "current_concept", None),
            **eval_boundary,
        )
        return await self._diagnostic_parse_eval_json(ai_response)

    async def _diagnostic_emit_question_for_index(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
    ) -> dict[str, Any]:
        ids = list(getattr(session, "diagnostic_topic_ids", None) or [])
        idx = int(getattr(session, "diagnostic_current_index", 0) or 0)
        if idx >= len(ids) or idx >= self._DIAG_MAX_PREREQ:
            resume = (
                getattr(session, "diagnostic_resume_question", None) or ""
            ).strip()
            self._diagnostic_reset_fields(session)
            await session.save()
            rq = resume or "Let's continue."
            return await self._answer_tutor_question_inner(
                session_id,
                student_id,
                rq,
                _suppress_diagnostic=True,
            )
        try:
            prereq_oid = PydanticObjectId(ids[idx])
        except Exception:
            resume = (
                getattr(session, "diagnostic_resume_question", None) or ""
            ).strip()
            self._diagnostic_reset_fields(session)
            await session.save()
            rq = resume or "Let's continue."
            return await self._answer_tutor_question_inner(
                session_id,
                student_id,
                rq,
                _suppress_diagnostic=True,
            )
        prereq_doc = await self._get_topic_or_teacher_topic(prereq_oid)
        topic_name = (
            (getattr(prereq_doc, "topic_name", None) or "this topic")
            if prereq_doc
            else "this topic"
        )
        cc = normalize_concept(getattr(session, "current_concept", None))
        concept_label = cc if cc else "(general)"
        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )
        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": student_id}
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
        notes = await rag_service.get_topic_notes(
            topic_id=prereq_oid,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
            current_concept=cc,
            user_query=None,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        context = await rag_service.build_context(
            notes,
            topic_id=prereq_oid,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        gen_q = (
            "Generate ONE very simple question to test understanding of:\n"
            f"concept: {concept_label}\n"
            f"topic: {topic_name}\n"
            "The question must be short and basic.\n"
            "Output only the question line, no preamble."
        )
        boundary = self._rag_prompt_boundary_kwargs(session, prereq_doc)
        generated = await rag_service.generate_prompt(
            question=gen_q,
            context=context if context and len(context.strip()) >= 20 else "",
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic_name,
            learning_state="explaining",
            user_intent="QUESTION_GENERATION",
            last_answer=None,
            is_followup=False,
            current_concept=cc,
            **boundary,
        )
        q_clean = (generated or "").strip().split("\n")[0].strip() or generated.strip()
        session.diagnostic_pending_question = q_clean[:5000]
        session.diagnostic_step = 1
        await session.save()
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        intro = "Let me check something first before we continue."
        combined = f"{intro}\n\n{q_clean}".strip()
        return {
            "type": "diagnostic_question",
            "question": q_clean,
            "message": combined,
            "answer": combined,
        }

    async def _diagnostic_short_explain_root(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        root_oid: PydanticObjectId,
        topic_name: str,
    ) -> str:
        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )
        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": student_id}
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
        notes = await rag_service.get_topic_notes(
            topic_id=root_oid,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
            current_concept=None,
            user_query=None,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        context = await rag_service.build_context(
            notes,
            topic_id=root_oid,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        root_doc = await self._get_topic_or_teacher_topic(root_oid)
        boundary = self._rag_prompt_boundary_kwargs(session, root_doc)
        short_q = (
            "Give a concise explanation (2-4 short paragraphs maximum) of the core ideas "
            f'for topic "{topic_name}". Use simple language for a struggling student. '
            "Stay strictly on this topic."
        )
        if not context or len(context.strip()) < 50:
            context = f"Topic: {topic_name}"
        body = await rag_service.generate_prompt(
            question=short_q,
            context=context,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic_name,
            learning_state="explaining",
            user_intent="EXPLAIN",
            last_answer=None,
            is_followup=False,
            current_concept=None,
            **boundary,
        )
        return (body or "").strip()

    async def _diagnostic_handle_pending_answer(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
    ) -> dict[str, Any] | None:
        session = await self.session_repository.get_by_id(session_id)
        if session is None or not getattr(session, "diagnostic_mode", False):
            return None
        if int(getattr(session, "diagnostic_step", 0) or 0) != 1:
            return None
        pending = (getattr(session, "diagnostic_pending_question", None) or "").strip()
        if not pending:
            self._diagnostic_reset_fields(session)
            await session.save()
            return None
        correct, _fb = await self._diagnostic_llm_evaluate_answer(
            session,
            session_id,
            student_id,
            pending,
            question,
        )
        session.diagnostic_pending_question = None
        if correct:
            session.diagnostic_attempt_count = 0
            session.diagnostic_current_index = (
                int(getattr(session, "diagnostic_current_index", 0) or 0) + 1
            )
            ids = list(getattr(session, "diagnostic_topic_ids", None) or [])
            if (
                session.diagnostic_current_index >= len(ids)
                or session.diagnostic_current_index >= self._DIAG_MAX_PREREQ
            ):
                resume = (
                    getattr(session, "diagnostic_resume_question", None) or ""
                ).strip()
                self._diagnostic_reset_fields(session)
                await session.save()
                rq = resume or "Let's continue."
                return await self._answer_tutor_question_inner(
                    session_id,
                    student_id,
                    rq,
                    _suppress_diagnostic=True,
                )
            await session.save()
            return await self._diagnostic_emit_question_for_index(
                session, session_id, student_id
            )
        idx = int(getattr(session, "diagnostic_current_index", 0) or 0)
        ids = list(getattr(session, "diagnostic_topic_ids", None) or [])
        root_sid = ids[idx] if idx < len(ids) else ids[-1] if ids else None
        if not root_sid:
            self._diagnostic_reset_fields(session)
            await session.save()
            return None
        try:
            root_oid = PydanticObjectId(root_sid)
        except Exception:
            self._diagnostic_reset_fields(session)
            await session.save()
            return None
        root_doc = await self._get_topic_or_teacher_topic(root_oid)
        root_name = (
            (getattr(root_doc, "topic_name", None) or "this topic")
            if root_doc
            else "this topic"
        )
        explain_body = await self._diagnostic_short_explain_root(
            session, session_id, student_id, root_oid, root_name
        )
        intro = (
            f"It seems you're having difficulty because of:\n{root_name}\n\n"
            f"Let me briefly explain this concept to help you.\n\n"
        )
        tail = (
            f"\n\nFor a better understanding, you should study:\n{root_name}\n\n"
            "You can continue here or revisit that topic."
        )
        full_msg = f"{intro}{explain_body}{tail}".strip()
        self._diagnostic_reset_fields(session)
        await session.save()
        return {
            "type": "root_cause",
            "topic_id": root_sid,
            "message": full_msg,
            "answer": full_msg,
        }

    async def _diagnostic_try_begin_or_emit(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        intent: str,
        is_followup_turn: bool,
        suppress_enter: bool,
    ) -> dict[str, Any] | None:
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            return None
        if getattr(session, "diagnostic_mode", False):
            if int(getattr(session, "diagnostic_step", 0) or 0) == 0:
                return await self._diagnostic_emit_question_for_index(
                    session, session_id, student_id
                )
            return None
        if suppress_enter:
            return None
        two_wrong = await self._diagnostic_teachback_two_recent_wrong(session_id)
        if not self._diagnostic_should_enter(
            user_input_lower=question.strip().lower(),
            intent=intent,
            is_followup_turn=is_followup_turn,
            two_quiz_wrong=two_wrong,
        ):
            return None
        filtered = await diagnostic_filtered_prereq_ids(session, self.topic_repository)
        if not filtered:
            # No prerequisites found — reset the attempt counter so the session
            # doesn't spin on this check every time the student makes a mistake.
            session.diagnostic_attempt_count = 0
            await session.save()
            return None
        session.diagnostic_mode = True
        session.diagnostic_step = 0
        session.diagnostic_topic_ids = filtered
        session.diagnostic_current_index = 0
        session.diagnostic_original_topic_id = str(session.topic_id)
        session.diagnostic_resume_question = question.strip()[:8000]
        session.diagnostic_pending_question = None
        await session.save()
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            return None
        return await self._diagnostic_emit_question_for_index(
            session, session_id, student_id
        )

    def _diagnostic_clear_quiz_expectation_for_teacher(self, session: Session) -> None:
        session.current_question = None
        session.current_mode = "normal"
        session.quiz_target_count = None
        session.quiz_asked_count = 0
        # Use "explaining" so the frontend auto-triggers the quiz for the
        # current concept once the diagnostic window closes.
        session.flow_state = "explaining"
        session.learning_state = "explaining"

    async def _diagnostic_teacher_quiz_or_wait_struggle(
        self,
        session: Session,
        session_id: PydanticObjectId,
        user_input_lower: str,
    ) -> bool:
        """Count struggle signals; return True only when attempt count reaches 2+."""
        fs = (getattr(session, "flow_state", None) or "").strip()
        in_waiting = fs == "waiting_for_question"
        in_live_quiz = fs == "quizzing" or getattr(
            session, "current_mode", "normal"
        ) == "quiz"
        if not (in_waiting or in_live_quiz):
            return False
        phrase = self._diagnostic_phrase_triggers(user_input_lower)
        if in_waiting:
            last_bad = await self._diagnostic_last_teachback_incorrect(session_id)
            struggle_signal = phrase or last_bad
        else:
            # Live quiz: only phrases here — eval not run yet; last-wrong would false-positive
            struggle_signal = phrase
        if not struggle_signal:
            return False
        session.diagnostic_attempt_count = int(
            getattr(session, "diagnostic_attempt_count", 0) or 0
        ) + 1
        await session.save()
        return session.diagnostic_attempt_count >= 2

    async def _diagnostic_enter_teacher_prereq_diagnostic_from_struggle(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        resume_message: str,
    ) -> dict[str, Any] | None:
        filtered = await diagnostic_filtered_prereq_ids(session, self.topic_repository)
        if not filtered:
            # No prerequisites found — reset counter to prevent repeated no-op checks.
            session.diagnostic_attempt_count = 0
            await session.save()
            return None
        self._diagnostic_clear_quiz_expectation_for_teacher(session)
        logger.info("DIAGNOSTIC TRIGGERED (quiz flow)")
        session.diagnostic_mode = True
        session.diagnostic_step = 0
        session.diagnostic_topic_ids = filtered
        session.diagnostic_current_index = 0
        session.diagnostic_original_topic_id = str(session.topic_id)
        session.diagnostic_resume_question = resume_message.strip()[:8000]
        session.diagnostic_pending_question = None
        await session.save()
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            return None
        return await self._diagnostic_emit_question_for_index(
            session, session_id, student_id
        )

    async def _diagnostic_try_enter_from_waiting_for_question_struggle(
        self,
        session: Session,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        suppress_enter: bool,
    ) -> dict[str, Any] | None:
        if suppress_enter:
            return None
        if not self._is_teacher_progression(session):
            return None
        if getattr(session, "diagnostic_mode", False):
            return None
        user_lower = question.strip().lower()
        if not await self._diagnostic_teacher_quiz_or_wait_struggle(
            session, session_id, user_lower
        ):
            return None
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            return None
        return await self._diagnostic_enter_teacher_prereq_diagnostic_from_struggle(
            session, session_id, student_id, question
        )

    async def answer_tutor_question(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
    ) -> str | dict:
        """
        Answer a student question using RAG. Topic is resolved from the question
        when possible, otherwise the session's topic is used.
        """
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if session.completion_status != "in_progress":
            raise ValueError("Session is not in progress")

        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty")

        if self._is_persistable_user_chat_message(question):
            await self._persist_chat_user(session_id, question)

        result = await self._answer_tutor_question_inner(
            session_id,
            student_id,
            question,
            _suppress_diagnostic=False,
        )
        await self._persist_board_turn(session_id, session, result)
        await self._persist_chat_assistant(session_id, result)
        progression_payload = None
        if isinstance(result, dict):
            session = await self.session_repository.get_by_id(session_id)
            if session is not None:
                from app.services.progression.plan_progress_coordinator import (
                    PlanProgressCoordinator,
                )

                progression_payload = await PlanProgressCoordinator().handle_tutor_result(
                    session, result
                )
        if isinstance(result, dict) and str(result.get("type")) == "completed":
            recommended_topics: Optional[list[dict[str, Any]]] = None
            try:
                _, recommended_topics = await self.end_session(session_id)
            except Exception:
                logger.exception(
                    "Natural topic completion pipeline failed for session_id=%s",
                    session_id,
                )
            return {
                **result,
                "_include_completion_payload": True,
                "_recommended_topics": recommended_topics,
                **({"progression": progression_payload} if progression_payload else {}),
            }
        if isinstance(result, dict) and progression_payload:
            return {**result, "progression": progression_payload}
        return result

    async def _answer_tutor_question_inner(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        *,
        _suppress_diagnostic: bool = False,
    ) -> str | dict:
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if session.completion_status != "in_progress":
            raise ValueError("Session is not in progress")

        if getattr(session, "diagnostic_mode", False) and not _suppress_diagnostic:
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")
            step = int(getattr(session, "diagnostic_step", 0) or 0)
            pending = (
                getattr(session, "diagnostic_pending_question", None) or ""
            ).strip()

            if pending:
                if step != 1:
                    session.diagnostic_step = 1
                    await session.save()
                logger.info("DIAGNOSTIC ANSWER HANDLING (priority)")
                diag_ans = await self._diagnostic_handle_pending_answer(
                    session_id, student_id, question
                )
                if diag_ans is not None:
                    return diag_ans
                session = await self.session_repository.get_by_id(session_id)
                if session is None:
                    raise ValueError("Session not found")
                if getattr(session, "diagnostic_mode", False):
                    logger.info(
                        "DIAGNOSTIC pending missing after handle; regenerating question"
                    )
                    return await self._diagnostic_emit_question_for_index(
                        session, session_id, student_id
                    )
            else:
                logger.info(
                    "DIAGNOSTIC pending missing; regenerating prerequisite question"
                )
                return await self._diagnostic_emit_question_for_index(
                    session, session_id, student_id
                )

        is_question = "?" in question

        user_input = question.strip().lower()
        is_quiz_mode = getattr(session, "current_mode", "normal") == "quiz"

        topic = await self._get_topic_or_teacher_topic(session.topic_id)

        # Short cluster reflection (between clusters); not quiz/teachback/clarity.
        if (
            self._is_teacher_progression(session)
            and getattr(session, "cluster_check_pending", False)
            and not getattr(session, "clarity_gate_active", False)
            and not is_quiz_mode
            and getattr(session, "current_mode", "normal") != "teachback"
        ):
            _cc_raw = question.strip()
            if _cc_raw and not _cc_raw.lower().startswith("__action:"):
                return await self._handle_cluster_check_input(
                    session,
                    session_id,
                    student_id,
                    question,
                    topic,
                )

        # ── Phase 7: Interactive retrieval — one-shot recall answer ──────────
        # Fires only when retrieval_active is True AND we are NOT already in
        # teachback/clarity-gate mode (clarity gate has higher priority).
        if (
            getattr(session, "retrieval_active", False)
            and not getattr(session, "clarity_gate_active", False)
            and getattr(session, "current_mode", "normal") != "teachback"
        ):
            return await self._handle_retrieval_answer(
                session, session_id, student_id, question
            )

        # ── Flow checkpoint before teachback ──────────────────────────────────
        # Reteach leaves current_mode=teachback for the follow-up question.
        # Pause, an identified checkpoint question, and continue must not be
        # scored as that teachback. concept_vtse_stage_done is not handled here.
        if topic is not None or (question or "").strip().lower().startswith("__action:flow_checkpoint"):
            _fc_early = await maybe_dispatch_flow_checkpoint(
                self._build_handler_context(),
                session,
                session_id,
                student_id,
                topic,
                question,
            )
            if _fc_early is not None:
                return _fc_early

        # ── Teachback (Clarity Gate): intercept before all other flow checks ─────
        if getattr(session, "current_mode", "normal") == "teachback":
            return await self._handle_teachback_input(
                session=session,
                session_id=session_id,
                student_id=student_id,
                user_input=question,
                topic=topic,
            )

        active_diagnostic = (
            getattr(session, "diagnostic_mode", False) and not _suppress_diagnostic
        )
        if not active_diagnostic:
            if self._is_teacher_progression(session) and not _suppress_diagnostic:
                diag_quiz_flow = (
                    await self._diagnostic_try_enter_from_waiting_for_question_struggle(
                        session,
                        session_id,
                        student_id,
                        question,
                        _suppress_diagnostic,
                    )
                )
                if diag_quiz_flow is not None:
                    return diag_quiz_flow
            teacher_reply = await self._teacher_handle_conversation(
                session, session_id, student_id, question, topic, is_quiz_mode
            )
        else:
            teacher_reply = None
        if active_diagnostic:
            is_quiz_mode = False
        if teacher_reply is not None:
            return teacher_reply
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if is_concept_notes_mode(session):
            cq_action_notes = self._teacher_flow_action(question)
            if cq_action_notes == "concept_notes_continue":
                topic_notes = topic or await self._get_topic_or_teacher_topic(
                    session.topic_id
                )
                if topic_notes is not None:
                    _ctx_notes = self._build_handler_context()
                    return await handle_concept_notes_continue(
                        _ctx_notes,
                        session,
                        session_id,
                        student_id,
                        topic_notes,
                    )
            return {"type": "noop"}
        if is_concept_questions_mode(session) or getattr(
            session, "flow_state", ""
        ) == "concept_questions":
            topic_cq = topic or await self._get_topic_or_teacher_topic(session.topic_id)
            if topic_cq is not None:
                cq_action = normalize_concept_question_action(
                    session,
                    action=self._teacher_flow_action(question),
                    student_text=(question or ""),
                )
                _ctx_cq = self._build_handler_context()
                return await handle_concept_questions_dispatch(
                    _ctx_cq,
                    session,
                    session_id,
                    student_id,
                    topic_cq,
                    student_text=(question or "").strip(),
                    action=cq_action,
                )
        if is_cluster_quiz_mode(session) or getattr(session, "flow_state", "") == "cluster_quiz":
            topic_cluster = topic or await self._get_topic_or_teacher_topic(session.topic_id)
            if topic_cluster is not None:
                cluster_action = normalize_cluster_quiz_action(
                    session,
                    action=self._teacher_flow_action(question),
                    student_text=(question or ""),
                )
                _ctx_cluster = self._build_handler_context()
                return await handle_cluster_quiz_dispatch(
                    _ctx_cluster,
                    session,
                    session_id,
                    student_id,
                    topic_cluster,
                    student_text=(question or "").strip(),
                    action=cluster_action,
                )
        if getattr(session, "diagnostic_mode", False) and not _suppress_diagnostic:
            is_quiz_mode = False
        learning_state = getattr(session, "learning_state", "explaining")
        state_at_entry = learning_state

        intent = self._classify_intent(user_input, is_quiz_mode)

        if is_quiz_mode and intent == "EXPLAIN":
            # ── Zone 3 hint-on-request (EXPLAIN path) ────────────────────────────
            # Single-word "hint" / "stuck" / "clue" gets classified as EXPLAIN.
            # In Zone 3 only, we intercept before exiting quiz mode and instead
            # return a one-sentence directional hint while keeping the quiz alive.
            _z3_explain_zone = int(getattr(session, "current_zone", 1) or 1)
            _q_text_for_hint = (getattr(session, "current_question", None) or "").strip()
            if (
                _z3_explain_zone == 3
                and _q_text_for_hint
                and self._is_zone3_hint_request(question)
            ):
                session.sus_hint_count = int(getattr(session, "sus_hint_count", 0) or 0) + 1
                await session.save()
                _hint = await self._generate_zone3_hint(
                    session, session_id, student_id, _q_text_for_hint
                )
                return {
                    "type": "quiz",
                    "message": f"💡 Hint: {_hint}",
                    "question": _q_text_for_hint,
                    "answer": "",
                    "source": "hint",
                    "concept": getattr(session, "current_concept", None) or "",
                }
            # ── Non-Zone-3 or non-hint EXPLAIN: original behaviour ────────────────
            session.current_mode = "normal"
            session.current_question = None
            session.learning_state = "explaining"
            session.quiz_target_count = None
            session.quiz_asked_count = 0
            await session.save()
            is_quiz_mode = False

        prior_last_answer_diag = getattr(session, "last_answer", None)
        is_followup_turn_diag = bool(prior_last_answer_diag) and intent in (
            "EXPLAIN",
            "UNKNOWN",
            "CONFIRM",
        )

        if not is_quiz_mode:
            diag_early = await self._diagnostic_handle_pending_answer(
                session_id, student_id, question
            )
            if diag_early is not None:
                return diag_early
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")

        detected_topic_for_concept = await self._detect_topic_from_query_simple(
            question,
            session.organization_id,
        )
        if not self._is_teacher_progression(session):
            await self._apply_session_concept_tracking(
                session,
                question,
                detected_topic_for_concept,
            )

        if not is_quiz_mode:
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")
            diag_late = await self._diagnostic_try_begin_or_emit(
                session_id,
                student_id,
                question,
                intent,
                is_followup_turn_diag,
                _suppress_diagnostic,
            )
            if diag_late is not None:
                return diag_late
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")

        if (
            not is_quiz_mode
            and intent == "CONFIRM"
            and not self._is_teacher_progression(session)
        ):
            if learning_state == "checking_understanding":
                session.quiz_target_count = None
                session.quiz_asked_count = 0
                await session.save()
                quiz = await self.generate_quiz_question(
                    session_id=session.id,
                    student_id=student_id,
                )
                session = await self.session_repository.get_by_id(session.id)
                if session is None:
                    raise ValueError("Session not found")
                session.current_mode = "quiz"
                session.current_question = quiz["question"]
                session.learning_state = "quizzing"
                await session.save()
                q_out = build_quiz_response(str(quiz["question"]))
                return {
                    "type": "quiz",
                    "message": q_out["message"],
                    "question": q_out["question"],
                    "answer": str(quiz.get("answer", "") or ""),
                    "source": str(quiz.get("source", "") or ""),
                    "concept": str(quiz.get("concept", "") or ""),
                }

        if is_quiz_mode and intent == "ANSWER":
            user_answer = question.strip()
            # Reject system/auto messages — never evaluate them as quiz answers.
            if not user_answer or user_answer == "." or user_answer.lower().startswith("__action:"):
                return {"type": "noop"}
            if not session.current_question:
                session.current_mode = "normal"
                session.current_question = None
                session.quiz_target_count = None
                session.quiz_asked_count = 0
                await session.save()
                return {
                    "type": "feedback",
                    "message": "I could not find the pending quiz question. Let's continue.",
                    "correct": False,
                }
            pending_quiz_question = session.current_question
            if bool(getattr(session, "cluster_quiz_active", False)):
                topic_cluster = topic or await self._get_topic_or_teacher_topic(
                    session.topic_id
                )
                if topic_cluster is not None:
                    cluster_action = normalize_cluster_quiz_action(
                        session,
                        action=self._teacher_flow_action(question),
                        student_text=user_answer,
                    )
                    _ctx_cluster = self._build_handler_context()
                    return await handle_cluster_quiz_dispatch(
                        _ctx_cluster,
                        session,
                        session_id,
                        student_id,
                        topic_cluster,
                        student_text=user_answer,
                        action=cluster_action,
                    )
            # ── Zone 3 hint-on-request (ANSWER path) ─────────────────────────────
            # Phrases like "give me a hint" are classified as ANSWER (not EXPLAIN)
            # because _classify_intent doesn't match them as struggle phrases.
            # Intercept here so they receive a directional hint, NOT evaluation.
            _z3_answer_zone = int(getattr(session, "current_zone", 1) or 1)
            if _z3_answer_zone == 3 and self._is_zone3_hint_request(user_answer):
                session.sus_hint_count = int(getattr(session, "sus_hint_count", 0) or 0) + 1
                await session.save()
                _hint_ans = await self._generate_zone3_hint(
                    session, session_id, student_id, pending_quiz_question
                )
                return {
                    "type": "quiz",
                    "message": f"💡 Hint: {_hint_ans}",
                    "question": pending_quiz_question,
                    "answer": "",
                    "source": "hint",
                    "concept": getattr(session, "current_concept", None) or "",
                }
            result = await self.evaluate_student_answer(
                session_id=session.id,
                student_id=student_id,
                question=pending_quiz_question,
                student_answer=user_answer,
            )
            quiz_attempt = int(getattr(session, "diagnostic_attempt_count", 0) or 0)
            quiz_mc_out = handle_misconception(
                result,
                mode="quiz",
                attempt=quiz_attempt,
            )
            quiz_action = str(quiz_mc_out.get("action") or "probe")
            if quiz_action not in {"confirm", "probe", "re_explain"}:
                quiz_action = "probe"
            quiz_is_confirm = quiz_action == "confirm"
            logger.info(
                "[QUIZ_MISCONCEPTION] session_id=%s attempt=%s action=%s",
                str(session_id),
                quiz_attempt,
                quiz_action,
            )
            if quiz_reply_seeks_help(question):
                result = dict(result)
                was_correct = bool(result.get("correct"))
                result["correct"] = False
                if was_correct and self.mastery_service is not None:
                    try:
                        await self.mastery_service.update_mastery(
                            student_id=student_id,
                            topic_id=session.topic_id,
                            concept=normalize_concept(
                                getattr(session, "current_concept", None)
                            ),
                            is_correct=False,
                            organization_id=session.organization_id,
                        )
                    except Exception:
                        pass
                session.current_mode = "normal"
                session.current_question = None
                if self._is_teacher_progression(session):
                    session.flow_state = "explaining"
                    session.learning_state = "explaining"
                else:
                    session.learning_state = "explaining"
                session.quiz_target_count = None
                session.quiz_asked_count = 0
                await session.save()

                topic_note_repository = TopicNoteRepository()
                video_subtitle_repository = VideoSubtitleRepository()
                topic_question_repository = TopicQuestionRepository()
                rag_service = RAGService(
                    topic_note_repository,
                    video_subtitle_repository,
                    topic_question_repository,
                    self.topic_repository,
                )
                student_profile = await StudentProfile.find_one(
                    {
                        "organization_id": session.organization_id,
                        "user_id": session.student_id,
                    }
                )
                teaching_style = (
                    student_profile.preferred_teaching_style
                    if student_profile is not None
                    else None
                )
                interests = (
                    student_profile.interests if student_profile is not None else []
                )
                interest_category = interests[0] if interests else "general"
                difficulty_level = (
                    student_profile.preferred_depth
                    if student_profile is not None
                    else None
                )
                topic_id_help = session.topic_id
                notes = await rag_service.get_topic_notes(
                    topic_id=topic_id_help,
                    organization_id=session.organization_id,
                    teaching_style=teaching_style,
                    interest_category=interest_category,
                    difficulty_level=difficulty_level,
                    current_concept=getattr(session, "current_concept", None),
                    user_query=question,
                    curriculum_class_id=getattr(session, "curriculum_class_id", None),
                    curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
                )
                context = await rag_service.build_context(
                    notes,
                    topic_id=topic_id_help,
                    organization_id=session.organization_id,
                    curriculum_class_id=getattr(session, "curriculum_class_id", None),
                    curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
                )
                topic_obj = await self._get_topic_or_teacher_topic(topic_id_help)
                help_boundary = self._rag_prompt_boundary_kwargs(session, topic_obj)
                help_mastery = await MasteryRepository().get_one(
                    mastery_record_filter(
                        session.organization_id,
                        student_id,
                        session.topic_id,
                        normalize_concept(getattr(session, "current_concept", None)),
                    )
                )
                help_mastery_score = (
                    float(help_mastery.mastery_score) if help_mastery is not None else None
                )
                help_prompt = (
                    f"The student was working on this quiz question but is stuck "
                    f'(they said: "{question}"):\n\n'
                    f"{pending_quiz_question}\n\n"
                    "Explain the ideas they need clearly and supportively, without "
                    "simply giving away the final answer if it is a single numeric result."
                )
                start_help = time.time()
                self._remember_learned_concept(
                    session, getattr(session, "current_concept", None)
                )
                explain_msg = await rag_service.generate_prompt(
                    question=help_prompt,
                    context=context if context and len(context.strip()) >= 50 else "",
                    student_profile=student_profile.model_dump()
                    if student_profile
                    else None,
                    topic_name=topic_obj.topic_name if topic_obj else None,
                    learning_state=getattr(session, "learning_state", "explaining"),
                    user_intent="UNKNOWN",
                    last_answer=None,
                    is_followup=False,
                    current_concept=getattr(session, "current_concept", None),
                    mastery_score=help_mastery_score,
                    last_answer_correct=False,
                    **help_boundary,
                )
                session.last_question = pending_quiz_question
                session.last_answer = explain_msg
                await session.save()
                await AIGenerationLog(
                    organization_id=session.organization_id,
                    student_id=student_id,
                    topic_id=topic_id_help,
                    session_id=session_id,
                    model_used=Settings.DEEPSEEK_MODEL,
                    task_type="qa",
                    tokens_used=0,
                    estimated_cost=0,
                    response_time_ms=int((time.time() - start_help) * 1000),
                ).insert()
                await EventRepository().create(
                    {
                        "organization_id": session.organization_id,
                        "session_id": session_id,
                        "student_id": student_id,
                        "event_type": SessionEventType.ANSWER,
                        "content": (explain_msg[:4000] if len(explain_msg) > 4000 else explain_msg),
                        "timestamp": datetime.utcnow(),
                    }
                )
                explain_body = build_explanation_response(
                    explain_msg,
                    "UNKNOWN",
                    state_at_entry,
                    optional_note=result.get("feedback"),
                )
                return {
                    "type": "explanation",
                    "message": explain_body,
                    "correct": result["correct"],
                }

            fresh = await self.session_repository.get_by_id(session_id)
            if fresh is None:
                raise ValueError("Session not found")
            session = fresh

            if self._is_teacher_progression(session) and getattr(
                session, "flow_state", ""
            ) == "quizzing" and bool(getattr(session, "cluster_quiz_active", False)):
                mc_out = quiz_mc_out
                topic_tq = await self._get_topic_or_teacher_topic(session.topic_id)
                next_c = self._get_next_concept(session, topic_tq)
                print(
                    "FLOW:",
                    session.flow_state,
                    "CURRENT:",
                    getattr(session, "current_concept", None),
                    "NEXT:",
                    next_c,
                )
                if quiz_action == "confirm":
                    # Quiz answered correctly — enter Teachback (Clarity Gate) before
                    # advancing to the next concept. Mastery is only confirmed once the
                    # student can explain the concept in their own words.
                    session.diagnostic_attempt_count = 0
                    session.current_mode = "teachback"
                    session.flow_state = "teachback"
                    session.teachback_required = True
                    session.current_question = None
                    await session.save()
                    cc_tb = getattr(session, "current_concept", None) or ""
                    return {
                        "type": "teachback",
                        "message": (
                            "Great answer! 🎉 Now let's make sure it's really clicked — "
                            "explain this concept in your own words, as if you were "
                            "teaching it to a friend."
                        ),
                        "current_concept": cc_tb,
                    }
                session.diagnostic_attempt_count = int(
                    0 if quiz_action == "confirm" else (quiz_attempt + 1)
                )
                await session.save()
                if (
                    quiz_action == "re_explain"
                    and not getattr(session, "diagnostic_mode", False)
                ):
                    # Repeated failures — run a prerequisite diagnostic before
                    # deciding how to continue (kept from original logic).
                    session = await self.session_repository.get_by_id(session_id)
                    if session is not None:
                        diag_out = await self._diagnostic_enter_teacher_prereq_diagnostic_from_struggle(
                            session,
                            session_id,
                            student_id,
                            user_answer,
                        )
                        if diag_out is not None:
                            return diag_out
                    session = await self.session_repository.get_by_id(session_id)
                    if session is None:
                        raise ValueError("Session not found")

                # Incorrect answer — enter Teachback (Clarity Gate) so the
                # student explains the concept in their own words before we
                # decide whether to re-quiz or advance.  This mirrors the
                # correct-answer path exactly; the teachback handler will
                # determine the next step based on the student's explanation.
                fb_line = build_feedback_response(
                    str(result.get("feedback") or ""),
                    False,
                    attempts=int(getattr(session, "diagnostic_attempt_count", 0) or 0),
                    sus_score=float(getattr(session, "sus_score", 50.0) or 50.0),
                )
                session.current_mode = "teachback"
                session.flow_state = "teachback"
                session.teachback_required = True
                session.current_question = None
                await session.save()
                cc_tb = getattr(session, "current_concept", None) or ""
                return {
                    "type": "teachback",
                    "message": (
                        f"{fb_line}\n\n"
                        "Before we continue, explain this concept in your own words — "
                        "teaching it back will help it click."
                    ),
                    "current_concept": cc_tb,
                }

            batch_target = getattr(session, "quiz_target_count", None)
            batch_asked = getattr(session, "quiz_asked_count", 0) or 0
            # Progression lock: keep the current quiz question active until confirm.
            if quiz_action == "probe":
                session.current_mode = "quiz"
                session.current_question = pending_quiz_question
                session.learning_state = "quizzing"
                session.diagnostic_attempt_count = int(
                    quiz_attempt + 1
                )
                await session.save()
                return {
                    "type": "quiz",
                    "message": "Which part of the concept do you think applies first here?",
                    "question": pending_quiz_question,
                    "answer": "",
                    "source": "probe",
                    "concept": getattr(session, "current_concept", None) or "",
                }
            if quiz_action == "re_explain":
                session.current_mode = "quiz"
                session.current_question = pending_quiz_question
                session.learning_state = "quizzing"
                session.diagnostic_attempt_count = quiz_attempt + 1
                await session.save()
                return {
                    "type": "quiz",
                    "message": (
                        f"{str(result.get('feedback') or '').strip()}\n\n"
                        "Quick re-explain: focus on the core concept, then answer this same question again."
                    ),
                    "question": pending_quiz_question,
                    "answer": "",
                    "source": "re_explain",
                    "concept": getattr(session, "current_concept", None) or "",
                }
            if batch_target is not None and batch_asked < batch_target:
                feedback_msg = build_feedback_response(
                    str(result.get("feedback") or ""),
                    quiz_is_confirm,
                    attempts=int(getattr(session, "diagnostic_attempt_count", 0) or 0),
                    sus_score=float(getattr(session, "sus_score", 50.0) or 50.0),
                )
                session.diagnostic_attempt_count = int(
                    0 if quiz_is_confirm else (quiz_attempt + 1)
                )
                next_quiz = await self.generate_quiz_question(
                    session_id=session.id,
                    student_id=student_id,
                )
                session = await self.session_repository.get_by_id(session_id)
                if session is None:
                    raise ValueError("Session not found")
                session.current_mode = "quiz"
                session.current_question = next_quiz["question"]
                session.learning_state = "quizzing"
                await session.save()
                n_done = getattr(session, "quiz_asked_count", 0) or 0
                q_out = build_quiz_response(str(next_quiz["question"]))
                lead = (
                    f"{feedback_msg}\n\n"
                    f"Let's connect this—here's another angle to think through "
                    f"({n_done} of {batch_target}):"
                )
                return {
                    "type": "quiz",
                    "message": lead,
                    "question": q_out["question"],
                    "answer": str(next_quiz.get("answer", "") or ""),
                    "source": str(next_quiz.get("source", "") or ""),
                    "concept": str(next_quiz.get("concept", "") or ""),
                }

            session.current_mode = "normal"
            session.current_question = None
            session.learning_state = "checking_understanding"
            session.diagnostic_attempt_count = int(
                0 if quiz_is_confirm else (quiz_attempt + 1)
            )
            if getattr(session, "quiz_target_count", None) is not None:
                session.quiz_target_count = None
                session.quiz_asked_count = 0
            await session.save()
            mastery = await MasteryRepository().get_one(
                mastery_record_filter(
                    session.organization_id,
                    student_id,
                    session.topic_id,
                    normalize_concept(getattr(session, "current_concept", None)),
                )
            )
            mastery_score = float(mastery.mastery_score) if mastery is not None else 50.0
            decision = await OrchestratorService().decide_next_action(
                mastery_score=mastery_score,
                last_answer_correct=quiz_is_confirm,
                has_recent_mistakes=not quiz_is_confirm,
            )
            if decision["action"] == "QUIZ":
                suggestion_text = "Want to try one more angle on this?"
            elif decision["action"] == "EXPLAIN":
                suggestion_text = "Want to walk through it again in simpler pieces?"
            else:
                suggestion_text = "What feels most useful from here?"
            feedback_msg = build_feedback_response(
                str(result.get("feedback") or ""),
                quiz_is_confirm,
                attempts=int(getattr(session, "diagnostic_attempt_count", 0) or 0),
                sus_score=float(getattr(session, "sus_score", 50.0) or 50.0),
            )
            return {
                "type": "feedback",
                "message": f"{feedback_msg}\n\n{suggestion_text}".strip(),
                "correct": quiz_is_confirm,
                "suggestion": decision["action"],
                "suggested_difficulty": decision["difficulty"],
            }

        if not is_quiz_mode and intent == "QUIZ":
            if self._is_teacher_progression(session):
                fsq_pre = getattr(session, "flow_state", "idle") or "idle"
                topic_qz = await self._get_topic_or_teacher_topic(session.topic_id)
                qz_msg = (
                    "__action:quiz"
                    if fsq_pre in ("checking_understanding", "explaining")
                    else question
                )
                qz_resp = await self._teacher_handle_conversation(
                    session,
                    session_id,
                    student_id,
                    qz_msg,
                    topic_qz,
                    False,
                )
                if qz_resp is not None:
                    return qz_resp
                # Fallback: quiz generation delegated, nothing left to return.
                session = await self.session_repository.get_by_id(session_id)
                if session is None:
                    raise ValueError("Session not found")
                return await self._generate_and_return_quiz(session, session_id, student_id)
            batch_n = extract_quiz_batch_count(question)
            if batch_n is not None:
                session.quiz_target_count = batch_n
                session.quiz_asked_count = 0
            else:
                session.quiz_target_count = None
                session.quiz_asked_count = 0
            await session.save()
            quiz = await self.generate_quiz_question(
                session_id=session.id,
                student_id=student_id,
            )
            session = await self.session_repository.get_by_id(session.id)
            if session is None:
                raise ValueError("Session not found")
            session.current_mode = "quiz"
            session.current_question = quiz["question"]
            session.learning_state = "quizzing"
            await session.save()
            q_out = build_quiz_response(str(quiz["question"]))
            return {
                "type": "quiz",
                "message": q_out["message"],
                "question": q_out["question"],
                "answer": str(quiz.get("answer", "") or ""),
                "source": str(quiz.get("source", "") or ""),
                "concept": str(quiz.get("concept", "") or ""),
            }

        # Zone 1 concept questions must never fall through to legacy RAG / 3-button UI.
        if not is_quiz_mode and (
            is_concept_questions_mode(session)
            or getattr(session, "flow_state", "") == "concept_questions"
        ):
            topic_cq = topic or await self._get_topic_or_teacher_topic(session.topic_id)
            if topic_cq is not None:
                cq_action = normalize_concept_question_action(
                    session,
                    action=self._teacher_flow_action(question),
                    student_text=(question or ""),
                )
                _ctx_cq = self._build_handler_context()
                return await handle_concept_questions_dispatch(
                    _ctx_cq,
                    session,
                    session_id,
                    student_id,
                    topic_cq,
                    student_text=(question or "").strip(),
                    action=cq_action,
                )

        # EXPLAIN, UNKNOWN, CONFIRM: RAG only — never orchestrator or auto-quiz (hard return below).
        skip_orchestrator_quiz = intent in ("EXPLAIN", "UNKNOWN", "CONFIRM")

        event_repository = EventRepository()
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.QUESTION,
                "content": question[:4000] if len(question) > 4000 else question,
                "timestamp": datetime.utcnow(),
            }
        )

        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
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

        topic_id = session.topic_id
        detected_topic_id = await rag_service.detect_topic_from_query(
            question,
            session.organization_id,
        )
        if detected_topic_id:
            topic_id = detected_topic_id

        notes = await rag_service.get_topic_notes(
            topic_id=topic_id,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
            current_concept=getattr(session, "current_concept", None),
            user_query=question,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        context = await rag_service.build_context(
            notes,
            topic_id=topic_id,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        if not context or len(context.strip()) < 50:
            return {
                "answer": "I don't have enough information on this topic yet.",
            }

        topic_for_prompt = await self._get_topic_or_teacher_topic(topic_id)
        start_time = time.time()
        prior_last_answer = getattr(session, "last_answer", None)
        is_followup_turn = bool(prior_last_answer) and intent in (
            "EXPLAIN",
            "UNKNOWN",
            "CONFIRM",
        )
        mastery_row = await MasteryRepository().get_one(
            mastery_record_filter(
                session.organization_id,
                student_id,
                topic_id,
                normalize_concept(getattr(session, "current_concept", None)),
            )
        )
        mastery_for_prompt = (
            float(mastery_row.mastery_score) if mastery_row is not None else None
        )
        ev_for_prompt = EventRepository()
        ev_list = await ev_for_prompt.get_session_events(session_id, limit=80)
        last_ans_correct_for_prompt = None
        for e in reversed(ev_list):
            if e.event_type == SessionEventType.ANSWER:
                last_ans_correct_for_prompt = getattr(e, "is_correct", None)
                break
        self._remember_learned_concept(
            session, getattr(session, "current_concept", None)
        )
        boundary_main = self._rag_prompt_boundary_kwargs(session, topic_for_prompt)
        if self._is_teacher_progression(session):
            self._teacher_debug_flow(session, topic_for_prompt)
        answer = await rag_service.generate_prompt(
            question=question,
            context=context,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic_for_prompt.topic_name if topic_for_prompt else None,
            learning_state=state_at_entry,
            user_intent=intent,
            last_answer=prior_last_answer if is_followup_turn else None,
            is_followup=is_followup_turn,
            current_concept=getattr(session, "current_concept", None),
            mastery_score=mastery_for_prompt,
            last_answer_correct=last_ans_correct_for_prompt,
            **boundary_main,
        )
        session.last_question = (question or "")[:5000] or None
        session.last_answer = (answer or "")[:12000] or None
        await session.save()

        if skip_orchestrator_quiz:
            response_time_ms = int((time.time() - start_time) * 1000)
            await AIGenerationLog(
                organization_id=session.organization_id,
                student_id=student_id,
                topic_id=topic_id,
                session_id=session_id,
                model_used=Settings.DEEPSEEK_MODEL,
                task_type="qa",
                tokens_used=0,
                estimated_cost=0,
                response_time_ms=response_time_ms,
            ).insert()
            await event_repository.create(
                {
                    "organization_id": session.organization_id,
                    "session_id": session_id,
                    "student_id": student_id,
                    "event_type": SessionEventType.ANSWER,
                    "content": (answer[:4000] if len(answer) > 4000 else answer),
                    "timestamp": datetime.utcnow(),
                }
            )
            session.learning_state = "explaining"
            if self._is_teacher_progression(session):
                session.flow_state = "explaining"
            await session.save()
            out_message = build_explanation_response(
                answer,
                intent,
                state_at_entry,
            )
            if self._is_teacher_progression(session):
                return {
                    "type": "understanding_check",
                    "message": out_message,
                    "current_concept": getattr(session, "current_concept", None)
                    or "",
                    "buttons": teacher_buttons(
                        [
                            ("understand", "I understand"),
                            ("ask_question", "I have a question"),
                            ("skip", "Skip"),
                        ]
                    ),
                }
            return {
                "type": "explanation",
                "message": out_message,
            }

        orchestrator = OrchestratorService()
        mastery_repository = MasteryRepository()
        mastery = await mastery_repository.get_one(
            mastery_record_filter(
                session.organization_id,
                student_id,
                topic_id,
                normalize_concept(getattr(session, "current_concept", None)),
            )
        )
        mastery_score = mastery.mastery_score if mastery else 50
        events = await EventRepository().get_many(
            filters={
                "session_id": session.id,
            },
            limit=50,
        )
        interaction_count = len(
            [e for e in events if e.event_type == SessionEventType.QUESTION]
        )
        last_answer_correct = None
        for e in reversed(events):
            if e.event_type == SessionEventType.ANSWER:
                last_answer_correct = getattr(e, "is_correct", None)
                break
        has_recent_mistakes = any(
            getattr(e, "is_correct", False) is False
            for e in events
            if e.event_type == SessionEventType.ANSWER
        )
        decision = await orchestrator.decide_next_action(
            mastery_score=mastery_score,
            last_answer_correct=last_answer_correct,
            has_recent_mistakes=has_recent_mistakes,
        )
        if is_question:
            decision["action"] = "EXPLAIN"
        if decision["action"] == "QUIZ":
            if interaction_count < 2 or last_answer_correct is None:
                decision["action"] = "EXPLAIN"
        if learning_state == "reviewing" and decision["action"] == "QUIZ":
            decision["action"] = "EXPLAIN"
        if self._is_teacher_progression(session) and decision["action"] == "QUIZ":
            decision["action"] = "EXPLAIN"
        print(f"[Orchestrator Decision]: {decision}")
        response_time_ms = int((time.time() - start_time) * 1000)

        await AIGenerationLog(
            organization_id=session.organization_id,
            student_id=student_id,
            topic_id=topic_id,
            session_id=session_id,
            model_used=Settings.DEEPSEEK_MODEL,
            task_type="qa",
            tokens_used=0,
            estimated_cost=0,
            response_time_ms=response_time_ms,
        ).insert()

        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.ANSWER,
                "content": (answer[:4000] if len(answer) > 4000 else answer),
                "timestamp": datetime.utcnow(),
            }
        )
        if decision["action"] == "QUIZ":
            session.quiz_target_count = None
            session.quiz_asked_count = 0
            await session.save()
            quiz = await self.generate_quiz_question(
                session_id=session.id,
                student_id=student_id,
            )
            session = await self.session_repository.get_by_id(session_id)
            if session is None:
                raise ValueError("Session not found")
            session.current_mode = "quiz"
            session.current_question = str(quiz["question"])
            session.learning_state = "quizzing"
            await session.save()
            q_out = build_quiz_response(str(quiz["question"]))
            return {
                "type": "quiz",
                "message": q_out["message"],
                "question": q_out["question"],
                "answer": str(quiz.get("answer", "") or ""),
                "source": str(quiz.get("source", "") or ""),
                "concept": str(quiz.get("concept", "") or ""),
                "difficulty": decision["difficulty"],
            }

        session.learning_state = "explaining"
        if self._is_teacher_progression(session):
            session.flow_state = "explaining"
        await session.save()
        out_message = build_explanation_response(
            answer,
            intent,
            state_at_entry,
        )
        if self._is_teacher_progression(session):
            return {
                "type": "understanding_check",
                "message": out_message,
                "current_concept": getattr(session, "current_concept", None)
                or "",
                "buttons": teacher_buttons(
                    [
                        ("understand", "I understand"),
                        ("ask_question", "I have a question"),
                        ("skip", "Skip"),
                    ]
                ),
            }
        return {
            "type": "explanation",
            "message": out_message,
        }

    async def generate_quiz_question(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        concept: str | None = None,
        *,
        force_single_concept: bool = False,
    ) -> dict:
        """Delegates to quiz_handler.generate_quiz_question via HandlerContext."""
        ctx = self._build_handler_context()
        return await _quiz_generate_question(
            ctx, session_id, student_id, concept, force_single_concept=force_single_concept
        )

    async def _generate_zone3_hint(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
        quiz_question: str,
    ) -> str:
        """Delegates to quiz_handler.generate_zone3_hint via HandlerContext."""
        ctx = self._build_handler_context()
        return await _quiz_generate_zone3_hint(ctx, session, session_id, student_id, quiz_question)

    async def _handle_retrieval_answer(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
        user_input: str,
    ) -> dict:
        """
        Evaluate a student's one-shot spaced-retrieval recall answer.

        Uses rule-based keyword matching (evaluate_multi_concept_explanation) so
        no LLM call is made.  The retrieval state is cleared immediately to
        prevent the flag from persisting across turns.
        """
        retrieval_concept: str = getattr(session, "retrieval_concept", None) or ""

        # Clear retrieval state before any async work (one-shot guarantee).
        session.retrieval_active = False
        session.retrieval_concept = None
        await session.save()

        if retrieval_concept:
            # Evaluation engine: LLM-based with rule-based fallback.
            # Generous threshold — recall is about prompting memory, not grading.
            eval_result = await _engine_evaluate(retrieval_concept, user_input)
            is_correct = bool(eval_result.get("correct")) or float(
                eval_result.get("score", 0)
            ) >= RETRIEVAL_PASS_THRESHOLD
            if is_correct:
                return {
                    "type": "retrieval_feedback",
                    "message": (
                        f"Great recall! Your understanding of **{retrieval_concept}** "
                        "is coming back nicely. Let's continue with today's concept."
                    ),
                    "correct": True,
                    "concept": retrieval_concept,
                }
            return {
                "type": "retrieval_feedback",
                "message": (
                    f"No worries — **{retrieval_concept}** is worth revisiting. "
                    "Let's continue with today's concept and we'll circle back to it later."
                ),
                "correct": False,
                "concept": retrieval_concept,
            }

        # Fallback: retrieval_concept was not stored (should not happen in practice).
        return {
            "type": "retrieval_feedback",
            "message": "Thanks for the recall attempt! Let's continue.",
            "correct": True,
        }

    async def _handle_teachback_input(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
        user_input: str,
        topic,
    ) -> dict:
        """Delegates to teachback_handler.handle_teachback_input via HandlerContext."""
        ctx = self._build_handler_context()
        result = await _teachback_handle_input(
            ctx,
            session,
            session_id,
            student_id,
            user_input,
            topic,
            teacher_explain_turn_fn=self._teacher_explain_turn,
        )
        # Auto-advance: after a successful concept teachback the session is set to
        # flow_state="idle". Without intervention the system just waits. Instead,
        # immediately fire the next concept's micro-teaching opening question so the
        # student doesn't have to send a blank message to continue.
        if (
            isinstance(result, dict)
            and result.get("type") == "explanation"
            and result.get("correct") is True
        ):
            session_reloaded = await self.session_repository.get_by_id(session_id)
            if (
                session_reloaded is not None
                and int(getattr(session_reloaded, "current_zone", 1) or 1) < 2
                and getattr(session_reloaded, "flow_state", "") == "idle"
                and getattr(session_reloaded, "current_mode", "") == "normal"
            ):
                try:
                    from app.services.pedagogy import vtse_opening_claim as _vtse_claim

                    _ctx2 = self._build_handler_context()
                    if not should_run_micro_teaching(session_reloaded):
                        return result
                    _c_idx = _vtse_claim.concept_index(session_reloaded)
                    _claimed = await _vtse_claim.atomic_claim_vtse_opening(
                        session_id,
                        concept_index=_c_idx,
                        set_flow_opening=True,
                    )
                    if _claimed is None:
                        return result
                    try:
                        opening = await teacher_micro_teaching_opening(
                            _ctx2,
                            session_reloaded,
                            session_id,
                            student_id,
                            topic,
                        )
                    except Exception:
                        await _vtse_claim.atomic_mark_vtse_opening_failed(
                            session_id, concept_index=_c_idx
                        )
                        raise
                    await _vtse_claim.atomic_mark_vtse_opening_ready(
                        session_id, concept_index=_c_idx
                    )
                    if opening:
                        if isinstance(opening, dict):
                            if str(opening.get("type") or "") == "vtse_opening_ack":
                                return result
                            opening_msg = str(opening.get("message", "")).strip()
                            opening_visual = opening.get("visual")
                        else:
                            opening_msg = str(opening).strip()
                            opening_visual = None
                        success_msg = str(result.get("message") or "Well done!").strip()
                        return {
                            "type": "explanation",
                            "message": success_msg + "\n\n" + opening_msg,
                            "correct": True,
                            "current_concept": result.get("current_concept", ""),
                            "visual": opening_visual,
                        }
                except Exception:
                    pass
        return result

    async def _handle_cluster_check_input(
        self,
        session: "Session",
        session_id: "PydanticObjectId",
        student_id: "PydanticObjectId",
        user_input: str,
        topic,
    ) -> dict:
        """Delegates to teachback_handler.handle_cluster_check_input."""
        ctx = self._build_handler_context()
        return await _teachback_handle_cluster_check_input(
            ctx,
            session,
            session_id,
            student_id,
            user_input,
            topic,
        )

    async def evaluate_student_answer(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        student_answer: str,
        reference_answer: str | None = None,
    ) -> dict:
        """Delegates to teachback_handler.evaluate_student_answer via HandlerContext."""
        ctx = self._build_handler_context()
        return await _teachback_evaluate_student_answer(
            ctx, session_id, student_id, question, student_answer, reference_answer
        )
