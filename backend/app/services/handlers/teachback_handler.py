"""
Teachback handler — standalone async functions extracted from SessionService.

All logic is IDENTICAL to the original private methods in session_service.py.
`self.*` references have been replaced with the HandlerContext `ctx` parameter
or with local pure-function helpers defined below.  SessionService is never
imported here.

`_teacher_explain_turn` cannot be extracted in this step (it orchestrates the
entire teacher explanation pipeline).  It is instead injected as a callable
(`teacher_explain_turn_fn`) so the handler remains decoupled from SessionService.

Public API (called from session_service.py):
    evaluate_student_answer(ctx, session_id, student_id, question, student_answer,
                            reference_answer=None) -> dict
    handle_teachback_input(ctx, session, session_id, student_id, user_input,
                           topic, teacher_explain_turn_fn) -> dict

Clarity Gate API (Phase 3 — only active when session.clarity_gate_active == True):
    evaluate_multi_concept_explanation(student_answer, concepts) -> dict
Cluster check (between clusters in teacher progression):
    handle_cluster_check_input(...) -> dict
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from beanie.odm.fields import PydanticObjectId

from app.core.config import Settings
from app.core.constants import CLARITY_GATE_PASS_THRESHOLD, CLUSTER_CHECK_PASS_THRESHOLD
from app.enums.learning_enums import SessionEventType
from app.models.curriculum.topics import Topic
from app.models.learning.mastery_records import normalize_concept
from app.models.learning.teachback_evaluations import TeachbackEvaluation
from app.models.teacher_topic import TeacherTopic
from app.repositories.event_repository import EventRepository
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.embedding_service import get_embedding
from app.services.misconception_service import handle_misconception
from app.services.rag_service import RAGService

if TYPE_CHECKING:
    from app.models.learning.sessions import Session
    from app.repositories.topic_repository import TopicRepository
    from app.services.handlers.context import HandlerContext

# Lazy-style import to avoid circular-dependency risk; resolved at call time.
# evaluate_answer: (concept, student_answer, reference_context) -> dict
from app.services.evaluation_engine import evaluate_answer as _engine_evaluate
from app.services.handlers.cluster_utils import (
    derive_current_cluster_index,
    flat_index_is_last_in_its_cluster,
    resolve_clusters,
    sync_current_cluster_index,
)
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator

logger = logging.getLogger(__name__)
_SUS_HISTORY_MAX = 7
_SUS_STREAK_NORM_MAX = 5
_SUS_CONFUSION_LOW_SCORE = 60.0


def _clamp_sus(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _update_sus_learning_signals(
    session: Session,
    *,
    correct: bool,
    evaluation_score: float,
    missing_points: list[str],
) -> None:
    """Update rolling SUS learning signals without changing teaching flow."""
    history = [bool(x) for x in (getattr(session, "sus_correct_history", None) or [])]
    history.append(bool(correct))
    session.sus_correct_history = history[-_SUS_HISTORY_MAX:]

    if correct:
        session.sus_streak = int(getattr(session, "sus_streak", 0) or 0) + 1
    else:
        session.sus_streak = 0

    if (not correct) and (
        float(evaluation_score) < _SUS_CONFUSION_LOW_SCORE or bool(missing_points)
    ):
        session.sus_confusion_count = int(
            getattr(session, "sus_confusion_count", 0) or 0
        ) + 1


def _refine_sus_score(session: Session, *, current_sus: float) -> float:
    """
    Compute a smoother SUS value from recent learning signals and blend it
    with the current SUS so existing update behavior remains intact.
    """
    history = [bool(x) for x in (getattr(session, "sus_correct_history", None) or [])]
    if history:
        accuracy_ratio = sum(1 for x in history if x) / float(len(history))
    else:
        accuracy_ratio = 0.5

    streak = int(getattr(session, "sus_streak", 0) or 0)
    streak_norm = min(streak, _SUS_STREAK_NORM_MAX) / float(_SUS_STREAK_NORM_MAX)

    confusion_count = int(getattr(session, "sus_confusion_count", 0) or 0)
    hint_count = int(getattr(session, "sus_hint_count", 0) or 0)
    confusion_penalty = min(25.0, confusion_count * 3.0)
    hint_penalty = min(10.0, hint_count * 1.5)

    computed_sus = (accuracy_ratio * 70.0) + (streak_norm * 30.0)
    computed_sus = _clamp_sus(computed_sus - confusion_penalty - hint_penalty)

    blended = (0.6 * float(current_sus)) + (0.4 * computed_sus)
    return round(_clamp_sus(blended), 1)

# ─────────────────────────────────────────────────────────────────────────────
# Private pure-function helpers (mirrors of SessionService static methods)
# ─────────────────────────────────────────────────────────────────────────────


def _is_teacher_progression(session: Session) -> bool:
    return (getattr(session, "total_concepts", 0) or 0) > 0


def _session_concept_sequence(
    session: Session, topic: Topic | TeacherTopic | None
) -> list[str]:
    kc = list(getattr(session, "key_concepts", None) or [])
    if kc:
        return [str(c).strip() for c in kc if c is not None and str(c).strip()]
    if topic is None:
        return []
    return [
        str(c).strip()
        for c in (topic.key_concepts or [])
        if c is not None and str(c).strip()
    ]


def _get_current_concept(
    session: Session, topic: Topic | TeacherTopic | None
) -> str | None:
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return None
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if idx < 0 or idx >= len(concepts):
        return None
    return concepts[idx]


def _get_next_concept(
    session: Session, topic: Topic | TeacherTopic | None
) -> str | None:
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return None
    idx = int(getattr(session, "current_concept_index", 0) or 0) + 1
    if idx < 0 or idx >= len(concepts):
        return None
    return concepts[idx]


def _rag_prompt_boundary_kwargs(
    session: Session, topic: Topic | TeacherTopic | None
) -> dict[str, Any]:
    if not _is_teacher_progression(session):
        return {}
    concepts = _session_concept_sequence(session, topic)
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


def _teacher_debug_flow(session: Session, topic: Topic | TeacherTopic | None) -> None:
    next_c = _get_next_concept(session, topic)
    print(
        "FLOW:",
        getattr(session, "flow_state", None),
        "CURRENT:",
        getattr(session, "current_concept", None),
        "NEXT:",
        next_c,
    )


def _remember_learned_concept(session: Session, concept: str | None) -> None:
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


async def _get_topic_or_teacher_topic_impl(
    topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic | TeacherTopic | None:
    t = await topic_repository.get_by_id(topic_id)
    if t is not None:
        return t
    return await TeacherTopic.get(topic_id)


# ─────────────────────────────────────────────────────────────────────────────
# Public async handler functions
# ─────────────────────────────────────────────────────────────────────────────


async def evaluate_student_answer(
    ctx: HandlerContext,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    question: str,
    student_answer: str,
    reference_answer: str | None = None,
) -> dict:
    """
    Evaluate a student's quiz or teachback answer using the LLM + RAG pipeline.

    Persists a TeachbackEvaluation record, updates session mastery fields and
    SUS score, and updates the mastery record via MasteryService.
    """
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found")
    if session.student_id != student_id:
        raise ValueError("Session does not belong to this student")
    if session.completion_status != "in_progress":
        raise ValueError("Session is not in progress")

    student_answer_stored = student_answer.strip()
    if not student_answer_stored:
        raise ValueError("Answer cannot be empty")

    event_repository = EventRepository()
    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.ANSWER,
            "content": student_answer_stored[:4000],
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
        ctx.topic_repository,
    )

    from app.models.identification.student_profiles import StudentProfile

    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )

    topic = await _get_topic_or_teacher_topic_impl(session.topic_id, ctx.topic_repository)
    current_concept = getattr(session, "current_concept", None)

    # ── Build rich evaluation context from topic notes ────────────────────────
    eval_context_parts: list[str] = []
    if topic:
        eval_context_parts.append(f"Topic: {topic.topic_name}")
    if current_concept:
        eval_context_parts.append(f"Concept: {current_concept}")
    try:
        concept_notes = await topic_note_repository.get_notes(
            session.topic_id,
            concept=current_concept,
            organization_id=session.organization_id,
            limit=4,
        )
        for n in concept_notes[:4]:
            nt = (getattr(n, "note_text", None) or "").strip()
            if nt:
                eval_context_parts.append(f"Curriculum note: {nt[:500]}")
    except Exception:
        pass  # Context fetch is best-effort

    context = "\n".join(eval_context_parts) if eval_context_parts else (
        f"Topic: {topic.topic_name}" if topic else ""
    )

    eval_boundary = _rag_prompt_boundary_kwargs(session, topic)
    if _is_teacher_progression(session):
        _teacher_debug_flow(session, topic)

    # ── Evaluation engine (LLM with rule-based fallback) ─────────────────────
    # Teachback aligned to taught content only (session-aware evaluation)
    _taught_points = [
        _canonicalize_taught_token(str(p))
        for p in (getattr(session, "taught_points", None) or [])
        if _canonicalize_taught_token(str(p))
    ]
    _eval_concept_source = (
        _taught_points
        if _taught_points
        else (getattr(session, "current_concept", None) or question)
    )
    _eng = await _engine_evaluate(
        concept=_eval_concept_source,
        student_answer=student_answer_stored,
        reference_context=context,
    )
    _eng_correct = bool(_eng["correct"])
    _correct_initial_from_engine = _eng_correct
    raw_score = float(_eng.get("score", 100.0 if _eng_correct else 0.0) or 0.0)
    feedback_engine = str(_eng["feedback"])
    _missing = [str(p) for p in (_eng.get("missing_points") or []) if str(p).strip()]
    _missing_raw_from_evaluator = list(_missing)
    correct = _eng_correct
    feedback = feedback_engine
    # Debugging teachback evaluation inconsistency (matching vs decision mismatch)
    _tb_debug_per_point: list[dict[str, Any]] = []
    _tb_debug_covered_ratio: float | None = None
    _tb_debug_word_count: int | None = None
    _tb_debug_covered_sorted: list[str] = []
    _tb_debug_coverage_pass: bool | None = None
    _tb_debug_theoretical_missing: list[str] = []
    if _taught_points:
        # Teachback evaluation aligned to taught_points (coverage-based, not length-based)
        _taught_norm = {str(p).strip().lower() for p in _taught_points}
        _semantic_match_taught = _build_semantic_matcher(student_answer_stored)
        _covered_points: set[str] = set()
        for t in _taught_norm:
            _alias_hit = _alias_match(student_answer_stored, t)
            _semantic_hit = _semantic_match_taught(t) if not _alias_hit else False
            _covered_by_answer = _alias_hit or _semantic_hit
            if _covered_by_answer:
                _covered_points.add(str(t).strip().lower())
            _tb_debug_per_point.append(
                {
                    "taught_token": t,
                    "alias_match": _alias_hit,
                    "semantic_match_used": _semantic_hit,
                }
            )
        _total_taught = max(1, len(_taught_points))
        _covered_ratio = len(_covered_points) / float(_total_taught)
        _ans_words = len(student_answer_stored.split())
        _tb_debug_covered_ratio = _covered_ratio
        _tb_debug_word_count = _ans_words
        _tb_debug_covered_sorted = sorted(_covered_points)
        _missing = [
            str(tp).strip()
            for tp in _taught_points
            if str(tp).strip().lower() not in _covered_points
        ]
        _tb_debug_theoretical_missing = list(_missing)
        _tb_debug_coverage_pass = _covered_ratio >= 0.6
        correct = _tb_debug_coverage_pass
        if correct:
            feedback = (
                "Nice work — you've covered the main ideas we focused on here."
            )
            if _missing:
                feedback = (
                    f"{feedback} What about {_missing[0].replace('_', ' ')}?"
                )
        else:
            disp = [m.replace("_", " ") for m in _missing[:3]]
            if len(disp) == 1:
                feedback = f"You've covered part of it. What about {disp[0]}?"
            elif len(disp) >= 2:
                feedback = (
                    f"You've covered part of it. What about {disp[0]} or {disp[1]}?"
                )
            else:
                feedback = (
                    "You've covered part of it. Try adding one more key idea "
                    "in your own words."
                )
    _correct_final = correct
    _failure_reasons: list[str] = []
    if not _correct_final:
        if _taught_points:
            if _tb_debug_covered_ratio is not None and _tb_debug_covered_ratio < 0.6:
                _failure_reasons.append(
                    f"coverage_below_0.6 (ratio={_tb_debug_covered_ratio:.4f})"
                )
        else:
            _failure_reasons.append("no_taught_points; engine_decides")
    # Debugging teachback evaluation inconsistency (matching vs decision mismatch)
    logger.info(
        "[TEACHBACK_EVAL_DEBUG] %s",
        json.dumps(
            {
                "session_id": str(session_id),
                "taught_points": _taught_points,
                "student_answer": student_answer_stored,
                "missing_raw_from_evaluator": _missing_raw_from_evaluator,
                "missing_taught_minus_covered": _missing if _taught_points else _missing,
                "per_point_matching": _tb_debug_per_point,
                "covered_points_final": _tb_debug_covered_sorted,
                "theoretical_missing_taught_minus_covered": _tb_debug_theoretical_missing,
                "coverage_ratio": _tb_debug_covered_ratio,
                "word_count": _tb_debug_word_count,
                "coverage_pass_gte_0.6": _tb_debug_coverage_pass,
                "correct_initial_from_engine": _correct_initial_from_engine,
                "correct_final": _correct_final,
                "evaluator_score": raw_score,
                "failure_reasons_if_incorrect": _failure_reasons,
                "note": "When taught_points set: pass and missing are coverage-only; score from evaluator.",
            },
            default=str,
        ),
    )
    if not _taught_points and not correct and _missing:
        missing_str = ", ".join(_missing[:3])
        feedback = f"{feedback} You might also want to include: {missing_str}."

    evaluation_score = raw_score if raw_score >= 0.0 else 0.0

    await TeachbackEvaluation(
        organization_id=session.organization_id,
        student_id=student_id,
        session_id=session_id,
        topic_id=session.topic_id,
        question_text=question.strip(),
        student_response=student_answer_stored,
        is_correct=correct,
        evaluation_score=evaluation_score,
        feedback=feedback,
        model_used=Settings.DEEPSEEK_MODEL,
        timestamp=datetime.utcnow(),
    ).insert()

    # Update session-level mastery control fields and SUS based on evaluation outcome.
    try:
        live_session = await ctx.session_repository.get_by_id(session_id)
        if live_session is not None:
            current_sus = float(getattr(live_session, "sus_score", 50.0) or 50.0)
            if correct:
                live_session.current_concept_mastered = True
                live_session.teachback_required = False
                live_session.sus_score = min(100.0, current_sus + 10.0)
            else:
                live_session.teachback_required = True
                live_session.sus_score = max(0.0, current_sus - 5.0)
            _update_sus_learning_signals(
                live_session,
                correct=correct,
                evaluation_score=evaluation_score,
                missing_points=_missing,
            )
            if int(getattr(live_session, "sus_confusion_count", 0) or 0) >= 3:
                # Teacher intervention flag (learning difficulty detected)
                live_session.teacher_flag = True
            live_session.sus_score = _refine_sus_score(
                live_session,
                current_sus=float(getattr(live_session, "sus_score", 50.0) or 50.0),
            )
            await live_session.save()
    except Exception:
        logger.exception(
            "Failed to update session mastery control fields for session_id=%s",
            session_id,
        )

    mastery_service = ctx.mastery_service
    if mastery_service is None:
        return {
            "correct": correct,
            "feedback": feedback,
        }
    try:
        mastery_record = await mastery_service.update_mastery(
            student_id=student_id,
            topic_id=session.topic_id,
            concept=normalize_concept(getattr(session, "current_concept", None)),
            is_correct=correct,
            organization_id=session.organization_id,
        )
    except Exception:
        mastery_record = None

    performance = "good" if correct else "struggling"
    score = mastery_record.mastery_score if mastery_record else None
    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.PERFORMANCE,
            "content": json.dumps(
                {
                    "performance": performance,
                    "score": score,
                }
            )[:4000],
            "timestamp": datetime.utcnow(),
        }
    )

    return {
        "correct": correct,
        "feedback": feedback,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Clarity Gate helpers (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

# Maximum number of evaluation rounds before the gate exits gracefully.
_CLARITY_GATE_MAX_STEPS = 3

# Minimum depth proxy (word-count scaled, 0–100) required to pass.
_CLARITY_GATE_PASS_DEPTH = 20.0
_SUS_LOW_THRESHOLD = 40.0
_SUS_HIGH_FAST_THRESHOLD = 75.0
_SUS_CLARITY_COMPLETE_THRESHOLD = 60.0
_TEACHBACK_SEMANTIC_MATCH_THRESHOLD = 0.65
_TEACHBACK_SEMANTIC_MATCH_SHORT_THRESHOLD = 0.72
_TEACHBACK_MISSING_SEMANTIC_THRESHOLD = 0.70


_TAUGHT_POINT_MATCH_ALIASES: dict[str, tuple[str, ...]] = {
    "growth": ("growth", "grow", "growing"),
    "respiration": ("respiration", "respire", "breath", "breathe", "breathing"),
    "reproduction": ("reproduction", "reproduce", "reproducing"),
    "photosynthesis": ("photosynthesis", "photosynth", "food making"),
    "carbon_dioxide": ("carbon dioxide", "co2"),
    "oxygen": ("oxygen",),
    "water": ("water",),
    "energy": ("energy",),
    "nutrition": ("nutrition", "nutrient", "food"),
    "movement": ("movement", "move", "moving"),
}


def _canonicalize_taught_token(raw: str) -> str:
    t = str(raw or "").strip().lower()
    if not t:
        return ""
    t = re.sub(r"[^a-z0-9_\s-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t in _TAUGHT_POINT_MATCH_ALIASES:
        return t
    for k, vals in _TAUGHT_POINT_MATCH_ALIASES.items():
        if t == k or any(v in t for v in vals):
            return k
    return t.replace(" ", "_")[:24]


def _missing_matches_taught(missing_item: str, taught_token: str) -> bool:
    m = str(missing_item or "").strip().lower()
    if not m:
        return False
    tt = _canonicalize_taught_token(taught_token)
    aliases = _TAUGHT_POINT_MATCH_ALIASES.get(tt, (tt.replace("_", " "),))
    return any(a in m for a in aliases) or tt in m.replace(" ", "_")


def _alias_match(student_answer: str, taught_token: str) -> bool:
    ans = str(student_answer or "").strip().lower()
    if not ans:
        return False
    tt = _canonicalize_taught_token(taught_token)
    aliases = _TAUGHT_POINT_MATCH_ALIASES.get(tt, (tt.replace("_", " "),))
    return any(a in ans for a in aliases) or tt in ans.replace(" ", "_")


def _split_semantic_chunks(text: str) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    parts = re.split(r"(?:\band\b|,|[.!?;])", raw)
    chunks = [re.sub(r"\s+", " ", p).strip() for p in parts if str(p).strip()]
    if not chunks:
        return [raw]
    return chunks


def _adaptive_semantic_threshold(text: str) -> float:
    words = len(str(text or "").strip().split())
    if words < 6:
        return _TEACHBACK_SEMANTIC_MATCH_SHORT_THRESHOLD
    return _TEACHBACK_SEMANTIC_MATCH_THRESHOLD


def _cosine_sim(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    return float(sum(float(a) * float(b) for a, b in zip(vec_a, vec_b)))


def _semantic_match(
    student_answer: str,
    taught_point: str,
    *,
    threshold: float | None = None,
) -> bool:
    """
    # Semantic matching for teachback (embedding-based, non-breaking enhancement)
    """
    try:
        text = str(student_answer or "").strip()
        a = get_embedding(text[:1000])
        b = get_embedding(str(taught_point or "").strip()[:300])
        if not a or not b:
            return False
        gate = (
            float(threshold)
            if threshold is not None
            else _adaptive_semantic_threshold(text)
        )
        return _cosine_sim(a, b) >= gate
    except Exception:
        return False


def _build_semantic_matcher(
    student_answer: str,
    *,
    threshold: float | None = None,
) -> Callable[[str], bool]:
    """
    Build a matcher that embeds answer once and caches taught-point embeddings.
    Falls back to False when embeddings are unavailable.
    """
    answer_text = str(student_answer or "").strip()
    gate = (
        float(threshold)
        if threshold is not None
        else _adaptive_semantic_threshold(answer_text)
    )
    chunks = _split_semantic_chunks(answer_text) or [answer_text]
    answer_chunk_embs: list[list[float]] = []
    try:
        for ch in chunks:
            emb = get_embedding(ch[:1000])
            if emb:
                answer_chunk_embs.append(emb)
    except Exception:
        answer_chunk_embs = []
    point_cache: dict[str, list[float]] = {}

    def _match(taught_point: str) -> bool:
        if not answer_chunk_embs:
            return False
        key = str(taught_point or "").strip().lower()
        if not key:
            return False
        if key not in point_cache:
            try:
                point_cache[key] = get_embedding(key[:300])
            except Exception:
                return False
        p_emb = point_cache.get(key) or []
        if not p_emb:
            return False
        best = max((_cosine_sim(a_emb, p_emb) for a_emb in answer_chunk_embs), default=0.0)
        return best >= gate

    return _match


def _mark_topic_complete_if_all_concepts_done(session: Session) -> None:
    """When current_concept_index has reached total_concepts, finish teaching phase."""
    tid = int(getattr(session, "total_concepts", 0) or 0)
    cid = int(getattr(session, "current_concept_index", 0) or 0)
    if tid > 0 and cid >= tid:
        session.current_concept = None
        session.current_mode = "normal"
        session.flow_state = "completed"


def _topic_clarity_gate_concept_list(
    session: Session, key_concepts: list[str]
) -> list[str]:
    """Topic-wide taught points for the gate, else the session key-concept sequence."""
    _ttp = [
        str(p).strip()
        for p in (getattr(session, "topic_taught_points", None) or [])
        if str(p).strip()
    ]
    if _ttp:
        return _ttp
    return [str(c).strip() for c in key_concepts if str(c).strip()]


def evaluate_multi_concept_explanation(
    student_answer: str,
    concepts: list[str],
) -> dict:
    """
    Rule-based evaluation of a student's explanation against multiple concepts.

    Each concept is considered *covered* if at least one of its significant
    keywords (length > 3) appears in the student's answer.  A short fallback
    uses the full concept string when no keyword is long enough.

    Args:
        student_answer: The student's free-text explanation.
        concepts:       Ordered list of concept names to check coverage for.

    Returns:
        dict with:
          coverage_score  (float 0–100) — fraction of concepts addressed.
          missing_concepts (list[str])  — concepts not detected in the answer.
          depth_score     (float 0–100) — proxy for answer richness (word count).
    """
    if not concepts:
        return {"coverage_score": 100.0, "missing_concepts": [], "depth_score": 0.0}

    answer_stripped = (student_answer or "").strip()
    if not answer_stripped:
        return {
            "coverage_score": 0.0,
            "missing_concepts": list(concepts),
            "depth_score": 0.0,
        }

    answer_lower = answer_stripped.lower()

    covered: list[str] = []
    missing: list[str] = []
    for concept in concepts:
        # Extract significant keywords from the concept name.
        keywords = [w for w in concept.lower().split() if len(w) > 3]
        if not keywords:
            keywords = [concept.lower()]
        if any(kw in answer_lower for kw in keywords):
            covered.append(concept)
        else:
            missing.append(concept)

    coverage_score = round(100.0 * len(covered) / len(concepts), 1)

    # Depth score: every 2 words → 1 point, capped at 100.
    word_count = len(answer_stripped.split())
    depth_score = round(min(100.0, word_count / 2.0), 1)

    return {
        "coverage_score": coverage_score,
        "missing_concepts": missing,
        "depth_score": depth_score,
    }


def _clarity_reasoning_score(
    student_answer: str,
    *,
    missing_points: list[str],
    evaluator_correct: bool,
) -> float:
    """Heuristic reasoning/completeness proxy normalized to 0–100."""
    text = (student_answer or "").strip()
    if not text:
        return 0.0
    words = text.split()
    wc = len(words)
    length_score = min(100.0, wc * 2.0)  # 50 words ~ full length credit
    reasoning_markers = (
        "because",
        "therefore",
        "so",
        "thus",
        "if",
        "then",
        "when",
        "hence",
        "which means",
    )
    lower = text.lower()
    marker_hits = sum(1 for m in reasoning_markers if m in lower)
    marker_score = min(100.0, marker_hits * 25.0)  # 4+ markers saturate
    punctuation_score = 100.0 if any(p in text for p in (".", ";", ":")) else 60.0
    base = min(100.0, (0.5 * length_score) + (0.35 * marker_score) + (0.15 * punctuation_score))

    # Ground reasoning by conceptual completeness so wording alone cannot inflate score.
    missing_count = len([m for m in (missing_points or []) if str(m).strip()])
    if missing_count == 0:
        base += 8.0
    else:
        base -= min(25.0, float(missing_count) * 6.0)
    if evaluator_correct:
        base += 4.0

    return round(max(0.0, min(100.0, base)), 1)


async def _handle_clarity_gate(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
) -> dict:
    """
    Multi-concept evaluation path — active only when session.clarity_gate_active
    is True.

    The student is asked to explain all concepts in session.clarity_gate_concepts.
    On each round the explanation is evaluated for coverage and depth.  Up to
    _CLARITY_GATE_MAX_STEPS rounds are allowed; the gate then exits gracefully.
    """
    from app.services.handlers.clarity_gate_service import evaluate_clarity_gate_answer

    gate_concepts: list[str] = list(getattr(session, "clarity_gate_concepts", None) or [])
    gate_step: int = int(getattr(session, "clarity_gate_step", 0) or 0)
    gate_question = (
        str(getattr(session, "clarity_gate_question", None) or "").strip()
        or "Explain how the main ideas from this zone fit together in your own words."
    )

    # Guard: gate misconfigured — deactivate silently and signal noop.
    if not gate_concepts:
        session.clarity_gate_active = False
        session.clarity_gate_step = None
        session.clarity_gate_concepts = None
        session.clarity_gate_question = None
        await session.save()
        return {"type": "noop"}

    # ── LLM evaluation grounded in full Zone whiteboard teaching ────────────
    _gate_eng = await evaluate_clarity_gate_answer(
        session,
        session_id,
        student_answer=user_input,
        question=gate_question,
        gate_concepts=gate_concepts,
    )
    coverage = float(_gate_eng["score"])
    missing: list[str] = list(_gate_eng["missing_points"])
    depth = float(_CLARITY_GATE_PASS_DEPTH + 1)
    # Refined clarity scoring (deduplicated signals + grounded reasoning)
    _total_gate = len(gate_concepts)
    _missing_count = len([m for m in missing if str(m).strip()])
    _covered_count = max(0, _total_gate - _missing_count)
    if _total_gate > 0:
        coverage_component = round((100.0 * _covered_count) / _total_gate, 1)
    else:
        coverage_component = 0.0
    evaluator_component = round(
        max(0.0, min(100.0, float(_gate_eng.get("score", 0.0) or 0.0))),
        1,
    )
    reasoning_component = _clarity_reasoning_score(
        user_input,
        missing_points=missing,
        evaluator_correct=bool(_gate_eng.get("correct", False)),
    )
    coverage_component = max(0.0, min(100.0, coverage_component))
    reasoning_component = max(0.0, min(100.0, reasoning_component))
    clarity_score = round(
        (0.4 * coverage_component)
        + (0.4 * evaluator_component)
        + (0.2 * reasoning_component),
        1,
    )
    session.clarity_score = max(0.0, min(100.0, clarity_score))

    # SUS-based progression stabilization (one-time reinforcement guard)
    _sus_now_gate = float(getattr(session, "sus_score", 50.0) or 50.0)
    _clarity_ready = coverage >= CLARITY_GATE_PASS_THRESHOLD and depth >= _CLARITY_GATE_PASS_DEPTH
    _clarity_sus_retry_done = bool(getattr(session, "clarity_sus_retry_done", False))
    _sus_blocks_completion = (
        _clarity_ready
        and _sus_now_gate < _SUS_CLARITY_COMPLETE_THRESHOLD
        and not _clarity_sus_retry_done
    )

    # ── Gate passed ───────────────────────────────────────────────────────────
    if _clarity_ready and (not _sus_blocks_completion):
        session.sus_score = min(
            100.0, float(getattr(session, "sus_score", 50.0) or 50.0) + 20.0
        )
        coordinator = ZoneTransitionCoordinator()
        entry = coordinator.complete_gate(session)
        await session.save()
        return coordinator.response_from_entry_result(
            entry,
            coverage=coverage,
            depth=depth,
        )

    new_step = gate_step + 1

    # ── Max rounds reached — exit gracefully ─────────────────────────────────
    if new_step >= _CLARITY_GATE_MAX_STEPS:
        session.teacher_flag = True
        coordinator = ZoneTransitionCoordinator()
        entry = coordinator.complete_gate(session)
        await session.save()
        return coordinator.response_from_entry_result(
            entry,
            coverage=coverage,
            depth=depth,
            missing=missing,
            graceful_exit=True,
        )

    # ── Prompt for another round ──────────────────────────────────────────────
    session.clarity_gate_step = new_step
    if _sus_blocks_completion:
        session.clarity_sus_retry_done = True
    await session.save()

    if _sus_blocks_completion:
        prompt_msg = (
            "Nice work — let's quickly reconnect the main ideas before we finish. "
            "Explain how the key concepts fit together in one clear chain."
        )
    elif missing:
        missing_str = ", ".join(f'"{c}"' for c in missing[:3])
        prompt_msg = (
            f"Good start! Could you also explain {missing_str}? "
            f"Try to cover these concepts in your own words."
        )
    else:
        prompt_msg = (
            "You're covering the right ideas! Can you go a bit deeper? "
            "Try to explain the 'why' behind each concept."
        )

    return {
        "type": "clarity_gate_prompt",
        "message": prompt_msg,
        "coverage_score": coverage,
        "missing_concepts": missing,
        "clarity_gate_step": new_step,
    }


async def handle_cluster_check_input(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic,
) -> dict:
    """
    One-turn reflection after completing all concepts in a cluster (not the
    final topic-wide Clarity Gate). Clears cluster_check_pending on exit.
    """
    if not getattr(session, "cluster_check_pending", False):
        return {"type": "noop"}

    raw = (user_input or "").strip()
    if not raw or raw.lower().startswith("__action:"):
        return {"type": "noop"}

    concepts = [
        str(c).strip()
        for c in (getattr(session, "cluster_check_concepts", None) or [])
        if c is not None and str(c).strip()
    ]
    cc_out = (getattr(session, "current_concept", None) or "").strip()

    eval_res = await _engine_evaluate(concepts, raw)
    score = int(eval_res.get("score", 0) or 0)
    passed = score >= CLUSTER_CHECK_PASS_THRESHOLD
    fb = str(eval_res.get("feedback") or "").strip()

    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found during cluster check")
    session.cluster_check_pending = False
    session.cluster_check_concepts = None
    session.flow_state = "idle"
    session.current_mode = "normal"
    session.current_question = None
    session.retrieval_active = False
    session.retrieval_concept = None
    await session.save()

    if passed:
        msg = (
            "Nice — that ties the cluster together well. "
            f"Let's connect this to **{cc_out}** as we keep going."
            if cc_out
            else "Nice — that ties the cluster together well. Let's keep going."
        )
    else:
        tail = (
            f"We will keep linking these ideas as we work on **{cc_out}**."
            if cc_out
            else "We will keep linking these ideas as we go."
        )
        intro = f"{fb} " if fb else "Thanks for sharing your thinking. "
        msg = f"{intro}{tail}".strip()

    return {
        "type": "explanation",
        "message": msg.strip(),
        "current_concept": cc_out,
    }


async def handle_teachback_input(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    user_input: str,
    topic,
    teacher_explain_turn_fn: Callable[..., Awaitable[Any]],
) -> dict:
    """
    Handle a student's teachback (explain-in-own-words) response.

    Called when session.current_mode == 'teachback'.  The student's free-text
    explanation is evaluated; if correct the concept is advanced, otherwise the
    concept is re-explained and another teachback attempt is requested.

    `teacher_explain_turn_fn` must be `self._teacher_explain_turn` from
    SessionService — injected to avoid a circular import.

    Phase 3 — Clarity Gate:
        When session.clarity_gate_active is True the function delegates
        immediately to _handle_clarity_gate() and the existing logic below is
        not executed.  Old sessions (clarity_gate_active == False) are
        completely unaffected.
    """
    # ── Clarity Gate branch (Phase 3) ─────────────────────────────────────────
    # This check comes first so that the gate intercepts every teachback message
    # when active.  The original flow below is only reached when the gate is off.
    if getattr(session, "clarity_gate_active", False):
        return await _handle_clarity_gate(
            ctx,
            session,
            session_id,
            student_id,
            user_input,
            topic,
            teacher_explain_turn_fn,
        )

    # ── Guard: reject non-student input ──────────────────────────────────────
    _raw = user_input.strip()
    if _raw.lower() == "__action:begin_zone_transition_gate":
        coordinator = ZoneTransitionCoordinator()
        payload = coordinator.activate_pending_gate(session)
        if payload.get("type") == "noop":
            return {"type": "noop"}
        await session.save()
        _teacher_debug_flow(session, topic)
        return payload

    if not _raw or _raw == ".":
        return {"type": "noop"}

    cluster_teachback_concepts = [
        str(c).strip()
        for c in (getattr(session, "teachback_concepts", None) or [])
        if str(c).strip()
    ]
    if cluster_teachback_concepts:
        if _raw.lower().startswith("__action:"):
            if _raw.lower() == "__action:cluster_teachback_reteach":
                from app.services.handlers.cluster_teachback_orchestrator import (
                    handle_cluster_teachback_reteach,
                )

                return await handle_cluster_teachback_reteach(
                    ctx,
                    session,
                    session_id,
                    student_id,
                    topic,
                    teacher_explain_turn_fn,
                )
            from app.services.handlers.flow_checkpoint_handler import (
                maybe_dispatch_flow_checkpoint,
            )

            # Pause, identified question, and continue belong to the open
            # checkpoint. concept_vtse_stage_done stays a noop so reteach
            # does not advance into Concept Check.
            checkpoint = await maybe_dispatch_flow_checkpoint(
                ctx,
                session,
                session_id,
                student_id,
                topic,
                _raw,
            )
            if checkpoint is not None:
                return checkpoint
            return {"type": "noop"}
        from app.services.handlers.cluster_teachback_orchestrator import (
            handle_cluster_teachback_input as _handle_cluster_teachback,
        )

        return await _handle_cluster_teachback(
            ctx,
            session,
            session_id,
            student_id,
            _raw,
            topic,
            teacher_explain_turn_fn,
        )

    if _raw.lower().startswith("__action:"):
        from app.services.handlers.flow_checkpoint_handler import (
            maybe_dispatch_flow_checkpoint,
        )

        checkpoint = await maybe_dispatch_flow_checkpoint(
            ctx,
            session,
            session_id,
            student_id,
            topic,
            _raw,
        )
        if checkpoint is not None:
            return checkpoint
        return {"type": "noop"}

    cc = getattr(session, "current_concept", None) or ""

    # ── Guard: reject non-student input (legacy per-concept teachback) ───────
    teachback_question = (
        f"Explain the concept: {cc}" if cc else "Explain the concept."
    )

    # Evaluate the explanation through the standard evaluation pipeline so that
    # TeachbackEvaluation records and mastery fields are updated automatically.
    result = await evaluate_student_answer(
        ctx,
        session_id=session_id,
        student_id=student_id,
        question=teachback_question,
        student_answer=user_input,
    )

    # Reload session — evaluate_student_answer has already updated mastery fields.
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found after teachback evaluation")

    topic_tq = await _get_topic_or_teacher_topic_impl(session.topic_id, ctx.topic_repository)

    attempts = int(getattr(session, "teachback_attempts", 0) or 0)
    mc_out = handle_misconception(result, mode="teachback", attempt=attempts)
    mc_action = str(mc_out.get("action") or "probe")
    if mc_action not in {"confirm", "probe", "re_explain"}:
        mc_action = "probe"
    logger.info(
        "[TEACHBACK_MISCONCEPTION] session_id=%s attempt=%s action=%s",
        str(session_id),
        attempts,
        mc_action,
    )

    # ── Teachback passed ──────────────────────────────────────────────────────
    if mc_action == "confirm":
        # SUS-based progression stabilization (one-time reinforcement guard)
        _sus_now = float(getattr(session, "sus_score", 50.0) or 50.0)
        _sus_reinf_done = bool(getattr(session, "sus_reinforcement_done", False))
        if _sus_now < _SUS_LOW_THRESHOLD and not _sus_reinf_done:
            session.current_mode = "teachback"
            session.flow_state = "teachback"
            session.teachback_required = True
            session.current_question = None
            session.sus_reinforcement_done = True
            await session.save()
            return {
                "type": "teachback_retry",
                "message": (
                    "You're close — let's tighten one piece before we move on. "
                    "In one short explanation, connect the core idea to why it works."
                ),
                "current_concept": cc,
            }
        # SUS > 75 keeps the current smooth pass path (no extra reinforcement turns).
        if _sus_now > _SUS_HIGH_FAST_THRESHOLD:
            pass

        # Zones are session-scoped: stay in Zone 1 for all concept teaching.
        # One successful teachback → advance concept (no Zone 2–4 loops per concept).
        session.sus_score = min(
            100.0, float(getattr(session, "sus_score", 50.0) or 50.0) + 15.0
        )
        session.current_mode = "normal"
        session.current_question = None
        session.teachback_required = False
        session.teachback_attempts = 0
        session.sus_reinforcement_done = False

        # ── Concept mastered → advance ─────────────────────────────────────────
        cc_done = _get_current_concept(session, topic_tq)
        _remember_learned_concept(session, cc_done)
        idx = int(session.current_concept_index or 0)
        session.current_concept_index = idx + 1
        session.current_concept_mastered = True
        from app.services.session_concept_tracking import sync_session_concept_fields

        sync_session_concept_fields(session)
        new_idx = int(session.current_concept_index or 0)

        kc = _session_concept_sequence(session, topic_tq)
        clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))

        if new_idx >= session.total_concepts:
            session.cluster_check_pending = False
            session.cluster_check_concepts = None
            session.retrieval_active = False
            session.retrieval_concept = None
            session.current_concept = None
            session.current_concept_id = None
            coordinator = ZoneTransitionCoordinator()
            payload = await coordinator.resolve_after_teachback_slice(
                session,
                topic_done=True,
                default_complete_message=(
                    "Excellent — you've worked through this session! Really well done. 🌟"
                ),
            )
            await session.save()
            _teacher_debug_flow(session, topic_tq)
            if payload.get("type") != "_continue":
                return payload
            return {
                "type": "completed",
                "message": (
                    "Excellent — you've worked through this session! Really well done. 🌟"
                ),
            }

        coordinator = ZoneTransitionCoordinator()
        mid_payload = await coordinator.resolve_after_teachback_slice(
            session,
            topic_done=False,
            default_complete_message="",
        )
        if mid_payload.get("type") != "_continue":
            await session.save()
            _teacher_debug_flow(session, topic_tq)
            return mid_payload

        # Advance to next concept.
        # Q&A already happened before the cluster quiz (triggered from explanation_handler
        # when micro-teaching closed). No second Q&A round here — just advance.
        from app.services.session_concept_tracking import sync_session_concept_fields

        sync_session_concept_fields(session)
        nc = session.current_concept
        session.learning_state = "explaining"
        await coordinator.sync_current_zone_for_index(session)
        session.flow_state = "idle"
        session.current_mode = "normal"
        session.student_questions_active = False
        session.current_step_in_concept = 0
        session.micro_last_connection_round = -1
        session.sus_reinforcement_done = False
        session.clarity_sus_retry_done = False
        session.current_question = None
        session.current_cluster_index = sync_current_cluster_index(
            key_concepts=kc,
            concept_clusters=getattr(session, "concept_clusters", None),
            current_concept_index=new_idx,
        )

        if len(clusters) > 1 and flat_index_is_last_in_its_cluster(idx, clusters):
            old_cidx = derive_current_cluster_index(idx, clusters)
            session.cluster_check_pending = True
            session.cluster_check_concepts = list(clusters[old_cidx])
            session.retrieval_active = False
            session.retrieval_concept = None
            await session.save()
            _teacher_debug_flow(session, topic_tq)
            return {
                "type": "cluster_check",
                "message": "Now explain how these ideas work together",
                "correct": True,
                "current_concept": session.current_concept or "",
                "cluster_concepts": list(clusters[old_cidx]),
            }

        await session.save()
        _teacher_debug_flow(session, topic_tq)

        return {
            "type": "explanation",
            "message": "Well done! Let's keep going.",
            "correct": True,
            "current_concept": session.current_concept or "",
        }

    # ── Teachback failed — re-explain then ask the student to try again ──────
    feedback_text = str(result.get("feedback") or "").strip()
    # teachback_attempts was already incremented by evaluate_student_answer.
    # Attempt progression safety: increment only when action is non-confirm.
    next_attempts = attempts + 1
    session.teachback_attempts = next_attempts
    if attempts >= 2:
        # Teacher intervention flag (learning difficulty detected)
        session.teacher_flag = True
    # SUS penalty computed once; applied in whichever sub-path saves the session.
    sus_after_fail = max(
        0.0, float(getattr(session, "sus_score", 50.0) or 50.0) - 10.0
    )

    # ── Attempt cap: give a final explanation and advance concept ─────────────
    if mc_action == "re_explain":
        exit_prompt = (
            f"The student has made {attempts} teachback attempt(s) for the concept "
            f'"{cc}" without demonstrating full understanding. '
            f"Give a short, clear final summary of this concept so they can move on."
        )
        # Put session in explaining state so _teacher_explain_turn works correctly.
        session.current_mode = "normal"
        session.flow_state = "explaining"
        session.learning_state = "explaining"
        session.current_question = None
        await session.save()

        exit_expl_text = ""
        if topic_tq is not None:
            try:
                body = await teacher_explain_turn_fn(
                    session,
                    session_id,
                    student_id,
                    topic_tq,
                    exit_prompt,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="explaining",
                    next_learning_state="explaining",
                )
                if isinstance(body, dict):
                    exit_expl_text = str(body.get("message") or "").strip()
                else:
                    exit_expl_text = str(body or "").strip()
            except Exception:
                logger.exception(
                    "Final teachback explanation failed for session_id=%s",
                    session_id,
                )

        if not exit_expl_text:
            exit_expl_text = f"Here is a brief summary of {cc}."

        # Reload session then advance to next concept.
        session = await ctx.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found after teachback exit explanation")

        cc_done = _get_current_concept(session, topic_tq)
        _remember_learned_concept(session, cc_done)
        idx = int(session.current_concept_index or 0)
        session.current_concept_index = idx + 1
        session.current_mode = "normal"
        session.current_question = None
        session.teachback_required = False
        session.current_concept_mastered = False
        session.teachback_attempts = 0
        session.sus_reinforcement_done = False
        session.sus_score = sus_after_fail
        from app.services.session_concept_tracking import sync_session_concept_fields

        sync_session_concept_fields(session)
        new_idx = int(session.current_concept_index or 0)
        kc = _session_concept_sequence(session, topic_tq)
        clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))

        if new_idx >= session.total_concepts:
            session.cluster_check_pending = False
            session.cluster_check_concepts = None
            session.retrieval_active = False
            session.retrieval_concept = None
            session.current_concept = None
            session.current_concept_id = None
            coordinator = ZoneTransitionCoordinator()
            payload = await coordinator.resolve_after_teachback_slice(
                session,
                topic_done=True,
                default_complete_message=(
                    "Excellent — you've worked through this session! Really well done. 🌟"
                ),
            )
            await session.save()
            _teacher_debug_flow(session, topic_tq)
            exit_msg = (
                f"{exit_expl_text}\n\n"
                "We'll move forward now and reconnect this idea later if needed."
            )
            if payload.get("type") != "_continue":
                if payload.get("type") == "clarity_gate_start":
                    payload = {
                        **payload,
                        "message": f"{exit_msg}\n\n{payload.get('message', '')}",
                    }
                return payload
            return {
                "type": "teachback_exit",
                "message": exit_msg,
                "current_concept": "",
            }
        else:
            session.flow_state = "idle"
            sync_session_concept_fields(session)
            nc = session.current_concept
            session.learning_state = "explaining"
            coordinator = ZoneTransitionCoordinator()
            await coordinator.sync_current_zone_for_index(session)
            session.current_step_in_concept = 0
            session.micro_last_connection_round = -1
            session.sus_reinforcement_done = False
            session.clarity_sus_retry_done = False
            session.current_cluster_index = sync_current_cluster_index(
                key_concepts=kc,
                concept_clusters=getattr(session, "concept_clusters", None),
                current_concept_index=new_idx,
            )
            if len(clusters) > 1 and flat_index_is_last_in_its_cluster(idx, clusters):
                old_cidx = derive_current_cluster_index(idx, clusters)
                session.cluster_check_pending = True
                session.cluster_check_concepts = list(clusters[old_cidx])
                session.retrieval_active = False
                session.retrieval_concept = None

        await session.save()
        _teacher_debug_flow(session, topic_tq)

        next_concept = getattr(session, "current_concept", None) or ""
        exit_msg = (
            f"{exit_expl_text}\n\n"
            "We'll move forward now and reconnect this idea later if needed."
        )
        if getattr(session, "cluster_check_pending", False):
            return {
                "type": "cluster_check",
                "message": f"{exit_msg}\n\nNow explain how these ideas work together",
                "current_concept": next_concept,
                "cluster_concepts": list(getattr(session, "cluster_check_concepts", None) or []),
            }
        return {
            "type": "teachback_exit",
            "message": exit_msg,
            "current_concept": next_concept,
        }

    # ── Probe path (Socratic only, no full re-explain) ────────────────────────
    if mc_action == "probe":
        session.current_mode = "teachback"
        session.flow_state = "explaining"
        session.learning_state = "explaining"
        session.current_question = None
        session.sus_score = sus_after_fail
        await session.save()

        probe_prompt = (
            f"The student gave an incorrect or partial teachback for concept '{cc}'.\n\n"
            f"Student answer:\n{user_input}\n\n"
            f"Evaluator feedback: {feedback_text}\n\n"
            "Output EXACTLY ONE Socratic follow-up question and NOTHING else.\n"
            "The output must end with '?'.\n"
            "Do NOT provide any explanation, correction statement, hint paragraph, or praise.\n"
            "Do NOT reveal the final answer.\n"
            "Keep it short, warm, and concept-focused."
        )
        probe_text = ""
        if topic_tq is not None:
            try:
                body = await teacher_explain_turn_fn(
                    session,
                    session_id,
                    student_id,
                    topic_tq,
                    probe_prompt,
                    intent="EXPLAIN",
                    state_at_entry="explaining",
                    next_flow_state="teachback",
                    next_learning_state="teachback",
                )
                if isinstance(body, dict):
                    probe_text = str(body.get("message") or "").strip()
                else:
                    probe_text = str(body or "").strip()
            except Exception:
                logger.exception(
                    "Socratic probe generation failed during teachback for session_id=%s",
                    session_id,
                )
        if not probe_text:
            probe_text = "What key idea from this concept do you think is missing in your answer?"
        elif "?" in probe_text:
            probe_text = f"{probe_text.split('?', 1)[0].strip()}?"
        else:
            probe_text = "What key idea from this concept do you think is missing in your answer?"

        session = await ctx.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found after teachback probe")
        session.current_mode = "teachback"
        session.flow_state = "teachback"
        session.learning_state = "teachback"
        session.teachback_required = True
        await session.save()
        return {
            "type": "teachback_retry",
            "message": probe_text,
            "current_concept": cc,
        }

    # ── Normal retry path — re-explain and ask again ──────────────────────────
    # Transition to explaining state so _teacher_explain_turn runs correctly.
    # current_mode stays "teachback" so that the re-explain call doesn't
    # accidentally enter the quiz flow; it is restored to "teachback" after.
    session.current_mode = "teachback"
    session.flow_state = "explaining"
    session.learning_state = "explaining"
    session.current_question = None
    session.sus_score = sus_after_fail
    await session.save()

    wrong_prompt = (
        f"The student attempted to explain the concept in their own words "
        f"but their explanation was incomplete or incorrect.\n\n"
        f'Concept: "{cc}"\n\n'
        f"Student explanation:\n{user_input}\n\n"
        f"Evaluation feedback: {feedback_text}\n\n"
        "Please re-explain the concept clearly and simply as one small coherent idea "
        "(usually 1-3 sentences), explicitly connect it to what was said before, "
        "then ask one easier follow-up question. Do not repeat the exact previous question."
    )

    expl_text = ""
    if topic_tq is not None:
        try:
            body = await teacher_explain_turn_fn(
                session,
                session_id,
                student_id,
                topic_tq,
                wrong_prompt,
                intent="EXPLAIN",
                state_at_entry="explaining",
                next_flow_state="explaining",
                next_learning_state="explaining",
            )
            if isinstance(body, dict):
                expl_text = str(body.get("message") or "").strip()
            else:
                expl_text = str(body or "").strip()
        except Exception:
            logger.exception(
                "Re-explanation failed during teachback retry for session_id=%s",
                session_id,
            )

    if not expl_text:
        expl_text = f"Let me re-explain {cc} for you."

    # Reset to teachback mode so the next message is intercepted correctly.
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found after teachback re-explanation")
    session.current_mode = "teachback"
    session.flow_state = "teachback"
    session.learning_state = "teachback"
    session.teachback_required = True
    await session.save()

    retry_msg = (
        f"You're on the right track — let me walk through it once more, "
        f"then give it another go.\n\n{expl_text}"
    )
    return {
        "type": "teachback_retry",
        "message": retry_msg,
        "current_concept": cc,
    }
