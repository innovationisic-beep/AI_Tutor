"""
Quiz handler — standalone async functions extracted from SessionService.

All logic is IDENTICAL to the original private methods in session_service.py.
`self.*` references have been replaced with the HandlerContext `ctx` parameter
or with local pure-function helpers defined below.  SessionService is never
imported here.

Public API (called from session_service.py):
    build_quiz_response(question) -> dict
    extract_quiz_batch_count(raw) -> int | None
    quiz_reply_seeks_help(user_input) -> bool
    generate_quiz_question(ctx, session_id, student_id, concept, *, force_single_concept) -> dict
    generate_and_return_quiz(ctx, session, session_id, student_id) -> dict
    generate_zone3_hint(ctx, session, session_id, student_id, quiz_question) -> str
"""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.enums.learning_enums import SessionEventType
from app.models.curriculum.topics import Topic
from app.models.identification.student_profiles import StudentProfile
from app.models.learning.mastery_records import (
    MasteryRecord,
    mastery_record_filter,
    normalize_concept,
)
from app.models.teacher_topic import TeacherTopic
from app.repositories.event_repository import EventRepository
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.embedding_service import get_embedding
from app.services.handlers.cluster_utils import (
    derive_current_cluster_index,
    resolve_clusters,
)
from app.services.rag_service import RAGService, _rank_by_similarity

if TYPE_CHECKING:
    from app.models.learning.sessions import Session
    from app.repositories.topic_repository import TopicRepository
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)


def _bank_question_is_usable(question_text: str | None) -> bool:
    from app.services.handlers.micro_interaction_meta import (
        is_meaningful_concept_question,
        normalize_concept_question_text,
    )

    raw = (question_text or "").strip()
    if not raw:
        return False
    normalized = normalize_concept_question_text(raw)
    return is_meaningful_concept_question(normalized)


def _normalize_generated_question(
    raw: str,
    *,
    concept: str | None,
    question_index: int = 0,
) -> str:
    from app.services.handlers.micro_interaction_meta import (
        is_meaningful_concept_question,
        normalize_concept_question_text,
    )

    normalized = normalize_concept_question_text(
        raw,
        concept=concept,
        question_index=question_index,
    )
    if is_meaningful_concept_question(normalized):
        return normalized
    return normalize_concept_question_text(
        None,
        concept=concept,
        question_index=question_index,
    )
QUIZ_INTROS = [
    "Now that we've connected these ideas, let's see how they fit together.",
    "Let's see how these ideas come together.",
    "Let's check how these pieces connect.",
    "Now let's try a couple of quick questions.",
]

# ─────────────────────────────────────────────────────────────────────────────
# Private pure-function helpers (mirrors of SessionService static methods)
# These are intentionally kept module-local to avoid importing SessionService.
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


def _get_next_concept(
    session: Session, topic: Topic | TeacherTopic | None
) -> str | None:
    concepts = _session_concept_sequence(session, topic)
    if not concepts:
        return None
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if idx + 1 >= len(concepts):
        return None
    return concepts[idx + 1]


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


def _normalize_question_difficulty(level: Any) -> str:
    from app.models.content.content_difficulty import (
        normalize_content_difficulty_from_storage,
    )
    return normalize_content_difficulty_from_storage(level)


def _question_difficulty_matches(level: Any, filt: str | dict) -> bool:
    lv = _normalize_question_difficulty(level)
    if isinstance(filt, str):
        return lv == filt
    if isinstance(filt, dict) and "$in" in filt:
        allowed = filt["$in"]
        return isinstance(allowed, list) and lv in allowed
    return True


async def _get_topic_or_teacher_topic_impl(
    topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic | TeacherTopic | None:
    t = await topic_repository.get_by_id(topic_id)
    if t is not None:
        return t
    return await TeacherTopic.get(topic_id)


def _teacher_buttons(items: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": a, "label": b} for a, b in items]


# ─────────────────────────────────────────────────────────────────────────────
# Public pure functions (exported to session_service.py)
# ─────────────────────────────────────────────────────────────────────────────


def build_quiz_response(question: str) -> dict[str, str]:
    q = (question or "").strip()
    intro = random.choice(QUIZ_INTROS)
    return {
        "message": intro,
        "question": q,
    }


def extract_quiz_batch_count(raw: str) -> int | None:
    """
    Detect e.g. 'ask 5 questions', 'quiz 3', '5 questions' (1–50).
    Only when the message looks quiz-related and contains a number.
    """
    t = (raw or "").strip().lower()
    if not re.search(r"\d", t):
        return None
    if not any(
        k in t
        for k in (
            "question",
            "questions",
            "quiz",
            "test",
            "ask me",
            "ask ",
            "give me",
        )
    ):
        return None
    m = re.search(r"\b([1-9]|[1-4]\d|50)\b", raw)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 50 else None


def quiz_reply_seeks_help(user_input: str) -> bool:
    """Quiz help: idk / don't know / explain / help (evaluate runs, then RAG only)."""
    s = user_input.strip().lower()
    if "idk" in s:
        return True
    if any(
        m in s
        for m in (
            "don't know",
            "dont know",
            "i don't know",
            "i dont know",
        )
    ):
        return True
    if "explain" in s or "help" in s:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Public async handler functions
# ─────────────────────────────────────────────────────────────────────────────


async def generate_quiz_question(
    ctx: HandlerContext,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    concept: str | None = None,
    *,
    force_single_concept: bool = False,
) -> dict:
    """
    Hybrid quiz: prefer unused TopicQuestionBank rows (scoped by concept when set),
    then fall back to AI. Tracks used_question_ids and last_questions (last 5).
    """
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found")
    if session.student_id != student_id:
        raise ValueError("Session does not belong to this student")
    if session.completion_status != "in_progress":
        raise ValueError("Session is not in progress")

    if force_single_concept and _is_teacher_progression(session):
        topic_for_idx = await _get_topic_or_teacher_topic_impl(
            session.topic_id, ctx.topic_repository
        )
        seq = _session_concept_sequence(session, topic_for_idx)
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        if seq and 0 <= idx < len(seq):
            concept = seq[idx]

    used_ids = [
        str(x)
        for x in (getattr(session, "used_question_ids", None) or [])
        if x is not None
    ]
    last_qs = list(getattr(session, "last_questions", None) or [])

    current_concept_norm = normalize_concept(getattr(session, "current_concept", None))
    current_concept_norm = (
        str(current_concept_norm).strip().lower()
        if current_concept_norm is not None
        else None
    )

    forced_concept_norm = normalize_concept(concept)
    forced_concept_norm = (
        str(forced_concept_norm).strip().lower()
        if forced_concept_norm is not None
        else None
    )

    locked_concept: str | None = None
    concept_pool_for_prompt: list[str] = []

    if force_single_concept:
        fc_only = forced_concept_norm or current_concept_norm
        if fc_only:
            fc_only = str(fc_only).strip().lower()
        if not fc_only:
            raise ValueError("Strict quiz requires a concept on the session")
        locked_concept = fc_only
        concept_pool_for_prompt = [fc_only]
    else:
        learned_raw = list(getattr(session, "learned_concepts", None) or [])
        learned_pool: list[str] = []
        seen: set[str] = set()
        for c in learned_raw:
            nc = normalize_concept(c)
            if nc is None:
                continue
            nc_l = str(nc).strip().lower()
            if not nc_l or nc_l in seen:
                continue
            seen.add(nc_l)
            learned_pool.append(nc_l)

        concept_pool_for_prompt = learned_pool if learned_pool else []
        if not concept_pool_for_prompt:
            if current_concept_norm:
                concept_pool_for_prompt = [current_concept_norm]
            elif forced_concept_norm:
                concept_pool_for_prompt = [forced_concept_norm]

        if concept_pool_for_prompt:
            if forced_concept_norm and forced_concept_norm in concept_pool_for_prompt:
                locked_concept = forced_concept_norm
            elif current_concept_norm and current_concept_norm in concept_pool_for_prompt:
                others = [
                    c for c in concept_pool_for_prompt if c != current_concept_norm
                ]
                if others:
                    locked_concept = random.choices(
                        [current_concept_norm] + others,
                        [0.6] + [0.4 / len(others)] * len(others),
                        k=1,
                    )[0]
                else:
                    locked_concept = current_concept_norm
            else:
                locked_concept = random.choice(concept_pool_for_prompt)

    strict_concept = bool(locked_concept)
    concept_for_bank = locked_concept if strict_concept else None
    mastery_concept = concept_for_bank
    mastery = await MasteryRecord.find_one(
        mastery_record_filter(
            session.organization_id,
            student_id,
            session.topic_id,
            mastery_concept,
        )
    )
    mastery_score = mastery.mastery_score if mastery is not None else 50.0
    if mastery is not None and mastery.confidence_score < 0.3:
        difficulty = "easy"
    elif mastery_score < 35:
        difficulty = "easy"
    elif mastery_score < 75:
        difficulty = "medium"
    else:
        difficulty = "hard"

    if difficulty == "easy":
        difficulty_level_filter: str | dict = {"$in": ["basic"]}
        db_difficulty_level: str | None = "basic"
    elif difficulty == "medium":
        difficulty_level_filter = "medium"
        db_difficulty_level = "medium"
    else:
        difficulty_level_filter = {"$in": ["hard"]}
        db_difficulty_level = "hard"

    # ── Zone overrides mastery-based difficulty ─────────────────────────────
    _session_zone = int(getattr(session, "current_zone", 1) or 1)
    if _session_zone <= 2:
        difficulty = "easy"
        difficulty_level_filter = {"$in": ["basic"]}
        db_difficulty_level = "basic"
    else:  # zone 3 or 4
        difficulty = "hard"
        difficulty_level_filter = {"$in": ["hard"]}
        db_difficulty_level = "hard"

    event_repository = EventRepository()
    topic_question_repository = TopicQuestionRepository()

    concept_pool_for_db = concept_pool_for_prompt or []

    asked_events = await event_repository.get_many(
        filters={
            "session_id": session_id,
            "event_type": SessionEventType.QUESTION,
        },
        limit=500,
    )
    asked_texts = {
        e.content.strip().lower()
        for e in asked_events
        if e.content
    }
    used_set = {str(uid) for uid in used_ids}

    concept_unused: dict[str, list] = {}
    for c in concept_pool_for_db:
        db_raw = await topic_question_repository.get_questions(
            session.topic_id,
            concept=c,
            organization_id=session.organization_id,
            difficulty_level=db_difficulty_level,
            limit=200,
        )
        if not db_raw:
            db_raw = await topic_question_repository.get_questions(
                session.topic_id,
                concept=c,
                organization_id=session.organization_id,
                limit=200,
            )
        db_strict = [
            q
            for q in db_raw
            if _question_difficulty_matches(
                getattr(q, "difficulty_level", None),
                difficulty_level_filter,
            )
        ]
        db_questions = db_strict if db_strict else db_raw

        unused = [
            q
            for q in db_questions
            if str(q.id) not in used_set
            and (q.question_text or "").strip().lower() not in asked_texts
            and _bank_question_is_usable(q.question_text)
        ]
        if unused:
            concept_unused[c] = unused

    if concept_unused:
        available_concepts = list(concept_unused.keys())

        current_norm = current_concept_norm
        if current_norm and current_norm in available_concepts:
            others = [c for c in available_concepts if c != current_norm]
            if others:
                selected_concept_used = random.choices(
                    [current_norm] + others,
                    [0.6] + [0.4 / len(others)] * len(others),
                    k=1,
                )[0]
            else:
                selected_concept_used = current_norm
        else:
            selected_concept_used = random.choice(available_concepts)

        unused_questions = concept_unused[selected_concept_used]
        unused_questions = unused_questions[:10]
        user_input = (getattr(session, "last_question", None) or "").strip()
        if not user_input:
            user_input = (locked_concept or "").strip()
        ranked_questions = list(unused_questions)
        if user_input:
            try:
                query_embedding = get_embedding(user_input[:1000])
                ranked_questions = _rank_by_similarity(
                    query_embedding, unused_questions, get_embedding
                )
                if not ranked_questions:
                    ranked_questions = list(unused_questions)
            except Exception:
                ranked_questions = list(unused_questions)
        selected = random.choice(ranked_questions[:5])

        used_ids.append(str(selected.id))
        last_qs = (last_qs + [(selected.question_text or "").strip()])[-5:]
        session.used_question_ids = used_ids
        session.last_questions = last_qs
        if getattr(session, "quiz_target_count", None) is not None:
            session.quiz_asked_count = (
                getattr(session, "quiz_asked_count", 0) or 0
            ) + 1
        await session.save()

        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.QUESTION,
                "content": selected.question_text[:4000],
                "timestamp": datetime.utcnow(),
            }
        )

        return {
            "question": _normalize_generated_question(
                (selected.question_text or "").strip(),
                concept=selected_concept_used,
            ),
            "answer": (getattr(selected, "correct_answer", None) or "").strip(),
            "explanation": (getattr(selected, "explanation", None) or "").strip(),
            "source": "db",
            "concept": selected_concept_used,
            "type": getattr(selected, "question_type", None) or "short_answer",
        }

    topic_note_repository = TopicNoteRepository()
    video_subtitle_repository = VideoSubtitleRepository()
    rag_service = RAGService(
        topic_note_repository,
        video_subtitle_repository,
        topic_question_repository,
        ctx.topic_repository,
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

    quiz_note_query = (getattr(session, "last_question", None) or "") or (
        locked_concept or ""
    )
    from app.services.curriculum.concept_vtse_context import load_concept_vtse_rag_context
    from app.services.session_concept_tracking import session_concept_id_for_rag

    template_context = await load_concept_vtse_rag_context(
        session_concept_id_for_rag(session),
        concept_label=locked_concept or "",
    )
    if (template_context or "").strip():
        context = template_context
    else:
        notes = await rag_service.get_topic_notes(
            topic_id=session.topic_id,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
            current_concept=locked_concept,
            user_query=str(quiz_note_query).strip() or None,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
            strict_concept=force_single_concept,
            zone=_session_zone,
        )
        context = await rag_service.build_context(
            notes,
            topic_id=session.topic_id,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )

    last_block = ""
    if last_qs:
        last_block = (
            "\n\nRecent questions already used in this session (do NOT repeat "
            "wording, structure, or scenario):\n"
            + "\n".join(f"- {x[:400]}" for x in last_qs[-5:])
        )

    if locked_concept:
        concepts_joined = ", ".join(concept_pool_for_prompt) or ""
        prioritize_concept = current_concept_norm or locked_concept or ""
        question_prompt = (
            f"Generate a question ONLY about the concept: '{locked_concept}'. "
            "Do NOT include any other topic, concept, or subject matter. "
            "Use the provided notes context strictly — do not invent facts or "
            "introduce examples outside the supplied material. "
            f"Use only these concepts as scope: {concepts_joined}. "
            f"Prioritize: {prioritize_concept}. "
            f"Difficulty level: {difficulty}. "
            "Do NOT repeat previous patterns, templates, numbers, or scenarios. "
            "Use different concrete examples than those already used. "
            "Return only the question — do NOT include the answer or any explanation."
            f"{last_block}"
        )
        if force_single_concept:
            question_prompt += (
                " Write ONE complete question the student can understand on its own. "
                "Always include a clear question stem (What, Which, How, Can, Is, Are). "
                "NEVER return only answer choices or fragments such as "
                "'a rock, a tree, or a spoon?' — include the stem, e.g. "
                "'Which of these is a living thing: a rock, a tree, or a spoon?'"
            )
    else:
        question_prompt = (
            f"Generate one {difficulty} level conceptual question for this topic. "
            "Base the question strictly on the provided notes context. "
            "Do NOT repeat previous patterns or templates. "
            "Use different numbers, quantities, and concrete examples than usual. "
            "Return only the question — do NOT include the answer or explanation."
            f"{last_block}"
        )

    # ── Zone + SUS adaptive quiz prompt ──────────────────────────────────────
    _quiz_zone = int(getattr(session, "current_zone", 1) or 1)
    _quiz_sus = float(getattr(session, "sus_score", 50.0) or 50.0)

    if _quiz_zone <= 2:
        question_prompt = (
            question_prompt
            + " Ask a clear, direct question that tests whether the student"
            + " understands the core definition or key fact of this concept."
            + " No scenario needed — simple and unambiguous."
        )

    elif _quiz_zone == 3:
        if _quiz_sus > 70.0:
            question_prompt = (
                question_prompt
                + " Write a rich, multi-part scenario (3–4 sentences) involving"
                + " two or more real-world examples of this concept."
                + " Ask the student to classify, compare, or reason about each"
                + " example and justify their answer. Embed NO hints."
                + " Competition-level difficulty — expect rigorous reasoning."
            )
        elif _quiz_sus <= 40.0:
            question_prompt = (
                question_prompt
                + " Write a challenging scenario (2–3 sentences) with two"
                + " examples of this concept. Embed one contextual clue in the"
                + " scenario wording that helps the student reason through it."
                + " Ask them to classify or explain each example."
                + " Break the question into two clear parts so it is approachable."
            )
        else:
            question_prompt = (
                question_prompt
                + " Write a scenario (2–3 sentences) with two real-world examples"
                + " of this concept. Ask the student to classify and briefly"
                + " justify each one. Include one subtle contextual detail that"
                + " helps guide their reasoning without giving the answer away."
            )

    elif _quiz_zone >= 4:
        question_prompt = (
            question_prompt
            + " Write a single open-ended question that pushes the student to"
            + " think beyond the concept itself — connecting it to a surprising"
            + " real-world context, a cross-disciplinary idea, limits, failure"
            + " modes, or where the usual explanation might break down."
            + " At least one angle should subtly challenge a default assumption."
            + " No scenario setup needed. No hints. Expect a creative,"
            + " thoughtful answer that shows genuine mastery."
        )

    if _is_teacher_progression(session):
        question_prompt = (
            question_prompt
            + " Phrase it like the next natural thing in a calm conversation—"
            + "do not start with 'Quick check', 'Pop quiz', or 'Ready for a question'."
        )

    topic_for_quiz = await _get_topic_or_teacher_topic_impl(
        session.topic_id, ctx.topic_repository
    )
    quiz_ai_boundary = _rag_prompt_boundary_kwargs(session, topic_for_quiz)
    if _is_teacher_progression(session):
        _teacher_debug_flow(session, topic_for_quiz)
    ai_output = await rag_service.generate_prompt(
        question=question_prompt,
        context=context,
        student_profile=student_profile.model_dump() if student_profile else None,
        topic_name=topic_for_quiz.topic_name if topic_for_quiz else None,
        learning_state=getattr(session, "learning_state", "explaining"),
        user_intent="QUESTION_GENERATION",
        last_answer=None,
        is_followup=False,
        current_concept=locked_concept,
        **quiz_ai_boundary,
    )
    ai_output = ai_output.strip()
    if ":" in ai_output:
        ai_output = ai_output.split(":", 1)[-1].strip()
    ai_output = _normalize_generated_question(
        ai_output,
        concept=locked_concept,
    )

    last_qs = (last_qs + [ai_output])[-5:]
    session.last_questions = last_qs

    q_hash = hash(ai_output.strip().lower())
    ai_q_key = f"ai:{q_hash}"
    existing_used = list(getattr(session, "used_question_ids", None) or [])
    if ai_q_key not in existing_used:
        existing_used.append(ai_q_key)
        session.used_question_ids = existing_used

    if getattr(session, "quiz_target_count", None) is not None:
        session.quiz_asked_count = (
            getattr(session, "quiz_asked_count", 0) or 0
        ) + 1
    await session.save()
    print(f"SELECTED: (ai-generated) session_id={session_id}")

    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.QUESTION,
            "content": ai_output[:4000],
            "timestamp": datetime.utcnow(),
        }
    )

    return {
        "question": ai_output,
        "answer": "",
        "source": "ai",
        "concept": locked_concept,
        "type": "short_answer",
    }


async def generate_and_return_quiz(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> dict:
    """
    Single, canonical path for generating a quiz for the current concept.

    Sets session.current_mode='quiz', flow_state='quizzing', current_question,
    saves, and returns {type:'quiz'}.  On failure returns understanding_check
    so the student can still interact.
    """
    try:
        quiz = await generate_quiz_question(
            ctx,
            session_id=session.id,
            student_id=student_id,
            concept=getattr(session, "current_concept", None),
            force_single_concept=True,
        )
        session = await ctx.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found after quiz generation")
        # Fresh micro-teaching cycle if the student returns to explain after this quiz.
        session.current_step_in_concept = 0
        session.micro_last_connection_round = -1
        session.current_mode = "quiz"
        session.current_question = quiz["question"]
        session.flow_state = "quizzing"
        session.learning_state = "quizzing"
        await session.save()
        q_out = build_quiz_response(str(quiz["question"]))
        return {
            "type": "quiz",
            "message": "",
            "question": q_out["question"],
            "current_concept": getattr(session, "current_concept", None) or "",
            "answer": str(quiz.get("answer", "") or ""),
            "source": str(quiz.get("source", "") or ""),
            "concept": str(quiz.get("concept", "") or ""),
        }
    except Exception:
        logger.exception(
            "generate_and_return_quiz failed for session_id=%s", session_id
        )
        session = await ctx.session_repository.get_by_id(session_id)
        cc = getattr(session, "current_concept", None) or "" if session else ""
        return {
            "type": "understanding_check",
            "message": "Before we continue, is there anything about this idea you'd like to clear up?",
            "current_concept": cc,
            "buttons": _teacher_buttons(
                [
                    ("understand", "I'm good — let's continue"),
                    ("explain_again", "Explain again"),
                    ("ask_question", "I have a question"),
                ]
            ),
        }


def _cluster_concepts_for_current_position(session: Session) -> list[str]:
    kc = [str(c).strip() for c in (getattr(session, "key_concepts", None) or []) if str(c).strip()]
    if not kc:
        return []
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    if not clusters:
        return []
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    cluster_idx = derive_current_cluster_index(idx, clusters)
    if cluster_idx < 0 or cluster_idx >= len(clusters):
        return []
    return [str(c).strip() for c in clusters[cluster_idx] if str(c).strip()]


async def generate_and_return_cluster_quiz(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> dict:
    """
    Start structured cluster quiz (3 questions: 2 descriptive + 1 MCQ).
    Questions appear in the cluster-quiz whiteboard panel (not chat Quick check).
    """
    from app.services.handlers.cluster_quiz_orchestrator import arm_cluster_quiz

    topic = await ctx.topic_repository.get_by_id(session.topic_id)
    if topic is None:
        from app.models.teacher_topic import TeacherTopic

        topic = await TeacherTopic.get(session.topic_id)
    if topic is None:
        return await generate_and_return_quiz(ctx, session, session_id, student_id)

    await arm_cluster_quiz(ctx, session, session_id, student_id, topic)
    session = await ctx.session_repository.get_by_id(session_id)
    if session is None:
        raise ValueError("Session not found after cluster quiz arm")
    cc = getattr(session, "current_concept", None) or ""
    return {
        "type": "feedback",
        "message": "Great work on this cluster! Let's see how well these ideas stick.",
        "correct": True,
        "current_concept": cc,
    }


async def generate_zone3_hint(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    quiz_question: str,
) -> str:
    """
    Generate a single-sentence directional hint for a Zone 3 problem.

    Contract:
      * NEVER reveals the answer or any calculation steps.
      * Always returns a non-empty string (falls back to a generic nudge).
      * Does NOT mutate session state — caller owns the return response.
    """
    try:
        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            ctx.topic_repository,
        )

        student_profile = await StudentProfile.find_one(
            {
                "organization_id": session.organization_id,
                "user_id": session.student_id,
            }
        )

        notes = await rag_service.get_topic_notes(
            topic_id=session.topic_id,
            organization_id=session.organization_id,
            teaching_style=None,
            interest_category="general",
            difficulty_level=None,
            current_concept=getattr(session, "current_concept", None),
            user_query=(quiz_question[:500] if quiz_question else ""),
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )
        context = await rag_service.build_context(
            notes,
            topic_id=session.topic_id,
            organization_id=session.organization_id,
            curriculum_class_id=getattr(session, "curriculum_class_id", None),
            curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
        )

        from app.services.curriculum.concept_vtse_context import load_concept_vtse_rag_context
        from app.services.session_concept_tracking import session_concept_id_for_rag

        template_context = await load_concept_vtse_rag_context(
            session_concept_id_for_rag(session),
            concept_label=(getattr(session, "current_concept", None) or ""),
        )
        if (template_context or "").strip():
            context = template_context

        topic_obj = await _get_topic_or_teacher_topic_impl(
            session.topic_id, ctx.topic_repository
        )
        hint_boundary = _rag_prompt_boundary_kwargs(session, topic_obj)

        hint_prompt = (
            f"The student is working on this competition-level problem:\n\n"
            f"{quiz_question}\n\n"
            "Give exactly ONE sentence as a directional hint that points them"
            " toward the right concept or reasoning approach to consider."
            " Do NOT give the answer, reveal the calculation, or walk through"
            " any steps. Keep it brief, warm, and encouraging."
        )

        hint_text = await rag_service.generate_prompt(
            question=hint_prompt,
            context=context if context and len(context.strip()) >= 50 else "",
            student_profile=(
                student_profile.model_dump() if student_profile else None
            ),
            topic_name=topic_obj.topic_name if topic_obj else None,
            learning_state="quizzing",
            user_intent="UNKNOWN",
            last_answer=None,
            is_followup=False,
            current_concept=getattr(session, "current_concept", None),
            **hint_boundary,
        )
        hint_text = hint_text.strip()
        if len(hint_text) > 300:
            first_sentence_end = hint_text.find(".")
            if 0 < first_sentence_end <= 300:
                hint_text = hint_text[: first_sentence_end + 1]
            else:
                hint_text = hint_text[:300]
        return (
            hint_text
            if hint_text
            else "Think about what principle from the explanation applies most directly here."
        )
    except Exception:
        return "Think about the key concept from this zone and how it applies to each part of the problem."
