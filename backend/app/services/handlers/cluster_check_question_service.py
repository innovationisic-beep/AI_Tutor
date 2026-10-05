"""
Structured cluster-end quiz: 2× descriptive + 1× MCQ per cluster.

DB first (typed filter across cluster concepts), then structured LLM fallback.
Questions must be grounded in cluster_taught_points — never invent counts or facts.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING, Any

from beanie.odm.fields import PydanticObjectId

from app.core.constants import (
    CLUSTER_CHECK_SLOT_TYPES,
    CLUSTER_QUESTIONS_PER_CLUSTER,
)
from app.enums.learning_enums import SessionEventType
from app.repositories.event_repository import EventRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.services.handlers.cluster_utils import resolve_clusters
from app.services.handlers.concept_check_question_service import (
    _db_difficulty_for_session,
    _fallback_mcq_from_taught_context,
    _pack_from_bank_row,
    _parse_json_object,
    _record_question_usage,
    _validate_mcq_payload,
    is_quality_mcq_pack,
)
from app.services.handlers.concept_check_question_types import (
    ConceptCheckQuestionType,
    has_blank_marker,
    infer_bank_question_type,
    is_descriptive_stem,
    resolve_mcq_correct_option,
)
from app.services.handlers.concept_taught_context import (
    effective_taught_item_count,
    is_broad_quiz_stem,
)
from app.services.handlers.quiz_handler import (
    _bank_question_is_usable,
    _question_difficulty_matches,
)
from app.services.handlers.teaching_transcript_service import (
    archetype_for_slot,
    build_cluster_quiz_taught_context,
    build_focus_assignment_block,
    build_rule_based_pack_from_focus,
    format_transcript_taught_block,
    is_meta_quiz_question,
    pack_matches_taught,
    pick_focus_fact,
    record_used_fact,
    used_fact_keys,
)

if TYPE_CHECKING:
    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)

ClusterCheckPack = dict[str, Any]


def required_type_for_slot(index: int) -> ConceptCheckQuestionType:
    idx = max(0, min(int(index), len(CLUSTER_CHECK_SLOT_TYPES) - 1))
    return CLUSTER_CHECK_SLOT_TYPES[idx]  # type: ignore[return-value]


def cluster_concepts_for_session(session: Session) -> list[str]:
    kc = [
        str(c).strip()
        for c in (getattr(session, "key_concepts", None) or [])
        if str(c).strip()
    ]
    if not kc:
        return []
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    if not clusters:
        return []
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    from app.services.handlers.cluster_utils import derive_current_cluster_index

    cluster_idx = derive_current_cluster_index(idx, clusters)
    if cluster_idx < 0 or cluster_idx >= len(clusters):
        return []
    return [str(c).strip() for c in clusters[cluster_idx] if str(c).strip()]


def concept_for_slot(cluster_concepts: list[str], index: int) -> str:
    if not cluster_concepts:
        return ""
    if index <= 0:
        return cluster_concepts[0]
    if index == 1 and len(cluster_concepts) > 1:
        return cluster_concepts[1]
    return cluster_concepts[-1]


async def _pick_cluster_quiz_from_bank(
    ctx: HandlerContext,
    session: Session,
    *,
    cluster_concepts: list[str],
    required_type: ConceptCheckQuestionType,
    taught_ctx: dict[str, Any] | None = None,
) -> ClusterCheckPack | None:
    """Pick next unused cluster_quiz bank row matching slot type across all cluster concepts."""
    if not cluster_concepts:
        return None

    topic_question_repository = TopicQuestionRepository()
    _, difficulty_filter = await _db_difficulty_for_session(session)
    _difficulty_label, db_difficulty_level = await _db_difficulty_for_session(session)

    used_set = {
        str(x) for x in (getattr(session, "used_question_ids", None) or []) if x
    }

    ordered_rows: list[Any] = []
    for concept in cluster_concepts:
        db_raw = await topic_question_repository.get_questions(
            session.topic_id,
            concept=concept,
            organization_id=session.organization_id,
            difficulty_level=db_difficulty_level,
            limit=200,
        )
        if not db_raw:
            db_raw = await topic_question_repository.get_questions(
                session.topic_id,
                concept=concept,
                organization_id=session.organization_id,
                limit=200,
            )
        staged = [
            q
            for q in db_raw
            if getattr(q, "quiz_stage", None) == "cluster_quiz"
        ]
        if not staged:
            db_all = await topic_question_repository.get_questions(
                session.topic_id,
                concept=concept,
                organization_id=session.organization_id,
                limit=200,
            )
            staged = [
                q
                for q in db_all
                if getattr(q, "quiz_stage", None) == "cluster_quiz"
            ]
        # Stable create order within each concept.
        staged.sort(
            key=lambda q: (
                getattr(q, "created_at", None) is None,
                getattr(q, "created_at", None) or datetime.min,
                str(getattr(q, "id", "")),
            )
        )
        ordered_rows.extend(staged)

    type_matched = [
        q for q in ordered_rows if infer_bank_question_type(q) == required_type
    ]
    strict = [
        q
        for q in type_matched
        if _question_difficulty_matches(
            getattr(q, "difficulty_level", None),
            difficulty_filter,
        )
    ]
    pool = strict if strict else type_matched

    for row in pool:
        if str(row.id) in used_set:
            continue
        if not _bank_question_is_usable(row.question_text):
            continue
        # Dedupe by bank id only. Do NOT block on asked_texts — concept-check and
        # cluster-quiz may intentionally share similar stems as separate bank rows.
        concept = str(getattr(row, "concept", "") or cluster_concepts[0])
        pack = _pack_from_bank_row(row, concept=concept)
        q = str(pack.get("question") or "").strip()
        if not q:
            continue
        # Trust authored cluster_quiz bank rows; only enforce structural shape.
        if required_type == "mcq":
            options = [str(o).strip() for o in (pack.get("options") or []) if str(o).strip()]
            correct = str(pack.get("correct_answer") or "").strip()
            if len(options) < 2 or correct not in options:
                continue
        elif required_type == "descriptive":
            if has_blank_marker(q) and str(pack.get("correct_answer") or "").strip():
                # Fill-in shape — leave for a different slot type.
                continue
        return pack
    return None


def build_cluster_taught_context(session: Session) -> dict[str, Any]:
    """Sync snapshot for validation paths; prefer async build_cluster_quiz_taught_context."""
    from app.services.handlers.teaching_transcript_service import (
        _cluster_base_taught_context,
    )

    return _cluster_base_taught_context(session)


def _cluster_pack_matches_taught(
    pack: ClusterCheckPack,
    taught_ctx: dict[str, Any],
    required_type: ConceptCheckQuestionType,
    *,
    focus_fact: str = "",
) -> bool:
    return pack_matches_taught(
        pack,
        taught_ctx,
        required_type=required_type,
        focus_fact=focus_fact,
    )


def _validate_descriptive_payload(data: dict[str, Any]) -> ClusterCheckPack | None:
    question = str(data.get("question") or "").strip()
    correct = str(data.get("correct_answer") or "").strip()
    explanation = str(data.get("explanation") or "").strip()
    options = list(data.get("options") or [])
    if len(question) < 12 or has_blank_marker(question):
        return None
    if len(options) >= 2:
        return None
    if not correct or len(correct) > 240:
        return None
    if is_descriptive_stem(question) and len(question) > 220:
        return None
    return {
        "question": question if question.endswith("?") else f"{question.rstrip('.')}?",
        "options": [],
        "correct_answer": correct,
        "explanation": explanation or correct,
        "type": "descriptive",
        "source": "ai",
    }


def _fallback_descriptive(
    concept: str,
    index: int,
    taught_ctx: dict[str, Any],
    *,
    focus_fact: str = "",
) -> ClusterCheckPack:
    c = (concept or "these ideas").strip()
    if focus_fact:
        ruled = build_rule_based_pack_from_focus(
            focus_fact=focus_fact,
            archetype=archetype_for_slot("descriptive", index),
            question_type="descriptive",
            concept=c,
            index=index,
            taught_ctx=taught_ctx,
        )
        if ruled is not None:
            return ruled  # type: ignore[return-value]

    facts = list(
        taught_ctx.get("teaching_facts")
        or taught_ctx.get("taught_points")
        or taught_ctx.get("steps")
        or []
    )
    if facts:
        ref = str(facts[index % len(facts)]).strip()
        return {
            "question": (
                f"In your own words, explain this idea from the lesson: "
                f"{ref.rstrip('.')}?"
            ),
            "options": [],
            "correct_answer": ref,
            "explanation": ref,
            "type": "descriptive",
            "source": "transcript_focus",
        }
    return {
        "question": f"Briefly explain one important idea about {c}.",
        "options": [],
        "correct_answer": f"A main idea taught about {c}.",
        "explanation": f"A main idea taught about {c}.",
        "type": "descriptive",
        "source": "template",
    }


async def _generate_cluster_mcq_pack(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    cluster_label: str,
    question_index: int,
    taught_ctx: dict[str, Any],
    taught_block: str,
    focus_fact: str,
    focus_key: str,
    archetype: str,
) -> ClusterCheckPack:
    from app.models.identification.student_profiles import StudentProfile
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.handlers.quiz_handler import _rag_prompt_boundary_kwargs
    from app.services.rag_service import RAGService

    last_qs = list(getattr(session, "last_questions", None) or [])
    last_block = ""
    if last_qs:
        last_block = (
            "\n\nDo NOT repeat these recent questions:\n"
            + "\n".join(f"- {x[:300]}" for x in last_qs[-5:])
        )

    step_count = effective_taught_item_count(taught_ctx)
    count_rule = ""
    if step_count > 0:
        count_rule = (
            f"\nCRITICAL: The lesson taught exactly {step_count} items. "
            "Do NOT ask about a different number of steps, characteristics, or parts.\n"
        )

    focus_block = ""
    if focus_fact:
        focus_block = build_focus_assignment_block(
            concept=cluster_label,
            focus_fact=focus_fact,
            archetype=archetype,
            question_type="mcq",
            taught_count=step_count,
            topic_anchor=str(taught_ctx.get("topic_anchor") or ""),
        )

    type_rules = (
        "Generate ONE multiple-choice question with exactly 4 options.\n"
        "Return JSON only:\n"
        '{"question":"...","options":["full option A text","full option B text",'
        '"full option C text","full option D text"],'
        '"correct_answer":"full option B text","explanation":"..."}\n'
        "Rules: one clear stem about the focus fact only; each option must be a complete "
        "factual sentence (at least 4 words — never single-word labels); exactly "
        "one correct option; distractors must be clearly false; "
        "correct_answer must exactly match one options[] string."
    )
    prompt = (
        f'Create a cluster quiz MCQ about "{cluster_label}".\n'
        f"{type_rules}\n"
        f"{count_rule}"
    )
    if focus_block:
        prompt += f"\n{focus_block}\n"
    else:
        prompt += "Use ONLY the lesson content below. Do not invent facts.\n"
    if taught_block:
        prompt += f"\nLESSON CONTENT:\n{taught_block}\n"
    prompt += last_block

    topic_question_repository = TopicQuestionRepository()
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
    context = taught_block or "No lesson content recorded for this cluster."
    boundary = _rag_prompt_boundary_kwargs(session, topic)

    for attempt in range(3):
        try:
            raw = await rag_service.generate_prompt(
                question=prompt,
                context=context,
                student_profile=student_profile.model_dump() if student_profile else None,
                topic_name=topic.topic_name if topic else None,
                learning_state="explaining",
                user_intent="QUESTION_GENERATION",
                current_concept=cluster_label,
                **boundary,
            )
            data = _parse_json_object(raw or "")
            if not data:
                continue
            pack = _validate_mcq_payload(data)
            if (
                pack
                and is_quality_mcq_pack(pack, taught_ctx)
                and _cluster_pack_matches_taught(
                    pack, taught_ctx, "mcq", focus_fact=focus_fact
                )
            ):
                pack["type"] = "mcq"
                pack["source"] = "ai"
                if focus_key:
                    pack["_focus_fact_key"] = focus_key
                return pack
        except Exception:  # noqa: BLE001
            logger.exception(
                "[CLUSTER_CHECK] LLM MCQ failed cluster=%s attempt=%s",
                cluster_label,
                attempt,
            )

    if focus_fact:
        ruled = build_rule_based_pack_from_focus(
            focus_fact=focus_fact,
            archetype=archetype,
            question_type="mcq",
            concept=cluster_label,
            index=question_index,
            taught_ctx=taught_ctx,
        )
        if ruled and _cluster_pack_matches_taught(
            ruled, taught_ctx, "mcq", focus_fact=focus_fact
        ):
            logger.warning(
                "[CLUSTER_CHECK] LLM MCQ failed; transcript-focus fallback cluster=%s",
                cluster_label,
            )
            ruled["type"] = "mcq"
            if focus_key:
                ruled["_focus_fact_key"] = focus_key
            return ruled  # type: ignore[return-value]

    taught_pack = _fallback_mcq_from_taught_context(
        cluster_label, question_index, taught_ctx
    )
    if taught_pack and _cluster_pack_matches_taught(
        taught_pack, taught_ctx, "mcq", focus_fact=focus_fact
    ):
        logger.warning(
            "[CLUSTER_CHECK] LLM MCQ failed; using taught-context fallback cluster=%s",
            cluster_label,
        )
        return taught_pack

    from app.services.handlers.concept_check_question_service import _fallback_mcq

    logger.error(
        "[CLUSTER_CHECK] LLM MCQ failed; no taught facts cluster=%s",
        cluster_label,
    )
    return _fallback_mcq(cluster_label, question_index)


async def _generate_cluster_llm_pack(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    concept: str,
    cluster_label: str,
    required_type: ConceptCheckQuestionType,
    question_index: int,
) -> ClusterCheckPack:
    taught_ctx = await build_cluster_quiz_taught_context(session_id, session)
    taught_block = format_transcript_taught_block(taught_ctx)
    taught_count = effective_taught_item_count(taught_ctx)
    focus_fact, focus_key = pick_focus_fact(
        taught_ctx,
        used_fact_keys=used_fact_keys(session, scope="cluster"),
        question_index=question_index,
    )
    archetype = archetype_for_slot(required_type, question_index)

    if required_type == "mcq":
        pack = await _generate_cluster_mcq_pack(
            ctx,
            session,
            session_id,
            topic,
            cluster_label=cluster_label,
            question_index=question_index,
            taught_ctx=taught_ctx,
            taught_block=taught_block,
            focus_fact=focus_fact,
            focus_key=focus_key,
            archetype=archetype,
        )
        pack["concept"] = concept
        if pack.get("type") == "mcq":
            return pack
        required_type = "descriptive"

    from app.models.identification.student_profiles import StudentProfile
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.handlers.quiz_handler import _rag_prompt_boundary_kwargs
    from app.services.rag_service import RAGService

    step_count = taught_count
    count_rule = ""
    if step_count > 0:
        count_rule = (
            f"\nCRITICAL: The lesson taught exactly {step_count} items. "
            "Do NOT ask about a different number of steps, characteristics, or parts.\n"
        )

    focus_block = ""
    if focus_fact:
        focus_block = build_focus_assignment_block(
            concept=concept,
            focus_fact=focus_fact,
            archetype=archetype,
            question_type="descriptive",
            taught_count=step_count,
            topic_anchor=str(taught_ctx.get("topic_anchor") or ""),
        )

    type_rules = (
        "Generate ONE short-answer question (student answers in 1-2 sentences).\n"
        "Return JSON only:\n"
        '{"question":"...","correct_answer":"brief reference answer","explanation":"..."}\n'
        "Rules: NOT multiple choice; NO blank markers; tests ONLY the focus fact; "
        "reference answer is one short sentence from the lesson."
    )
    last_qs = list(getattr(session, "last_questions", None) or [])
    last_block = ""
    if last_qs:
        last_block = (
            "\n\nDo NOT repeat these recent questions:\n"
            + "\n".join(f"- {x[:300]}" for x in last_qs[-5:])
        )
    prompt = (
        f'Create a cluster quiz question about "{concept}" '
        f'(cluster: {cluster_label}).\n'
        f"{type_rules}\n"
        f"{count_rule}"
    )
    if focus_block:
        prompt += f"\n{focus_block}\n"
    else:
        prompt += "Use ONLY the lesson content below. Do not invent facts.\n"
    if taught_block:
        prompt += f"\nLESSON CONTENT:\n{taught_block}\n"
    prompt += last_block

    topic_question_repository = TopicQuestionRepository()
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
    context = taught_block or "No lesson content recorded for this cluster."
    boundary = _rag_prompt_boundary_kwargs(session, topic)

    for attempt in range(3):
        try:
            raw = await rag_service.generate_prompt(
                question=prompt,
                context=context,
                student_profile=student_profile.model_dump() if student_profile else None,
                topic_name=topic.topic_name if topic else None,
                learning_state="explaining",
                user_intent="QUESTION_GENERATION",
                current_concept=concept,
                **boundary,
            )
            data = _parse_json_object(raw or "")
            if not data:
                continue
            pack = _validate_descriptive_payload(data)
            if pack and _cluster_pack_matches_taught(
                pack, taught_ctx, "descriptive", focus_fact=focus_fact
            ):
                pack["concept"] = concept
                pack["source"] = "ai"
                if focus_key:
                    pack["_focus_fact_key"] = focus_key
                return pack
        except Exception:  # noqa: BLE001
            logger.exception(
                "[CLUSTER_CHECK] LLM descriptive failed concept=%s attempt=%s",
                concept,
                attempt,
            )

    pack = _fallback_descriptive(
        concept, question_index, taught_ctx, focus_fact=focus_fact
    )
    pack["concept"] = concept
    if focus_key:
        pack["_focus_fact_key"] = focus_key
    return pack


async def load_cluster_check_question(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    index: int,
) -> ClusterCheckPack:
    """Load one structured cluster-quiz question for the given slot index."""
    cluster_concepts = cluster_concepts_for_session(session)
    if not cluster_concepts:
        raise ValueError("Cluster quiz requires key_concepts on session")

    required = required_type_for_slot(index)
    concept = concept_for_slot(cluster_concepts, index)
    cluster_label = ", ".join(cluster_concepts[:4])
    taught_ctx = await build_cluster_quiz_taught_context(session_id, session)

    pack = await _pick_cluster_quiz_from_bank(
        ctx,
        session,
        cluster_concepts=cluster_concepts,
        required_type=required,
        taught_ctx=taught_ctx,
    )
    # Authored bank packs are trusted; do not discard for AI grounding rules.

    if pack is None:
        pack = await _generate_cluster_llm_pack(
            ctx,
            session,
            session_id,
            topic,
            concept=concept,
            cluster_label=cluster_label,
            required_type=required,
            question_index=index,
        )

    if pack is None or (
        str(pack.get("source") or "") != "db"
        and not _cluster_pack_matches_taught(pack, taught_ctx, required)
    ):
        focus_fact, _ = pick_focus_fact(
            taught_ctx,
            used_fact_keys=used_fact_keys(session, scope="cluster"),
            question_index=index,
        )
        pack = (
            _fallback_mcq_from_taught_context(cluster_label, index, taught_ctx)
            if required == "mcq"
            else _fallback_descriptive(
                concept, index, taught_ctx, focus_fact=focus_fact
            )
        )

    focus_key = str(pack.pop("_focus_fact_key", "") or "").strip()
    if focus_key:
        record_used_fact(session, focus_key, scope="cluster")

    pack["type"] = required

    await _record_question_usage(session, pack)

    event_repository = EventRepository()
    await event_repository.create(
        {
            "organization_id": session.organization_id,
            "session_id": session_id,
            "student_id": student_id,
            "event_type": SessionEventType.QUESTION,
            "content": str(pack.get("question") or "")[:4000],
            "timestamp": datetime.utcnow(),
        }
    )

    logger.info(
        "[CLUSTER_CHECK] loaded index=%s type=%s source=%s concept=%s",
        index,
        pack.get("type"),
        pack.get("source"),
        concept,
    )
    return pack


def apply_cluster_check_pack_to_session(
    session: Session, pack: ClusterCheckPack, index: int
) -> None:
    qtype = required_type_for_slot(index)
    options = list(pack.get("options") or [])
    question = str(pack.get("question") or "")[:5000]
    if has_blank_marker(question):
        qtype = "descriptive"
        options = []
    session.current_question = question
    answer = str(pack.get("correct_answer") or pack.get("explanation") or "").strip()
    if qtype == "mcq" and answer and options:
        resolved = resolve_mcq_correct_option(answer, options)
        if resolved:
            answer = resolved
    session.cluster_quiz_question_answer = answer[:5000] if answer else None
    session.cluster_quiz_question_type = (
        qtype if qtype in ("mcq", "descriptive") else "descriptive"
    )
    session.cluster_quiz_question_options = (
        [str(o).strip() for o in options if str(o).strip()][:10]
        if qtype == "mcq"
        else []
    )
    session.cluster_quiz_index = max(
        0, min(index, CLUSTER_QUESTIONS_PER_CLUSTER - 1)
    )
    session.cluster_quiz_followup = False
    session.cluster_quiz_clarifying = False
    session.cluster_quiz_pending_advance = False


def clear_cluster_check_question_fields(session: Session) -> None:
    session.cluster_quiz_question_answer = None
    session.cluster_quiz_question_type = None
    session.cluster_quiz_question_options = []
    session.current_question = None
