"""
Structured concept-check questions: 2× MCQ + 1× fill-in-the-blank per concept.

DB first (typed filter), then structured LLM fallback. Does not affect cluster quiz.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from beanie.odm.fields import PydanticObjectId

from app.core.constants import CONCEPT_CHECK_SLOT_TYPES, CONCEPT_QUESTIONS_PER_CONCEPT
from app.enums.learning_enums import SessionEventType
from app.repositories.event_repository import EventRepository
from app.repositories.topic_note_repository import TopicNoteRepository
from app.repositories.topic_question_repository import TopicQuestionRepository
from app.repositories.video_subtitle_repository import VideoSubtitleRepository
from app.services.embedding_service import get_embedding
from app.services.handlers.concept_check_question_types import (
    BLANK_MARKER_RE,
    ConceptCheckQuestionType,
    has_blank_marker,
    infer_bank_question_type,
    is_descriptive_stem,
    is_strong_fill_in_answer,
    normalize_answer_text,
)
from app.services.handlers.concept_taught_context import (
    effective_taught_item_count,
    is_broad_quiz_stem,
)
from app.services.handlers.teaching_transcript_service import (
    archetype_for_slot,
    build_concept_quiz_taught_context,
    build_focus_assignment_block,
    build_rule_based_pack_from_focus,
    format_transcript_taught_block,
    is_meta_quiz_question,
    pack_matches_taught,
    pick_focus_fact,
    record_used_fact,
    used_fact_keys,
    taught_fact_strings,
)
from app.services.handlers.quiz_handler import (
    _bank_question_is_usable,
    _question_difficulty_matches,
    _rag_prompt_boundary_kwargs,
)
from app.services.rag_service import RAGService, _rank_by_similarity

if TYPE_CHECKING:
    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)

ConceptCheckPack = dict[str, Any]


def required_type_for_slot(index: int) -> ConceptCheckQuestionType:
    idx = max(0, min(int(index), len(CONCEPT_CHECK_SLOT_TYPES) - 1))
    return CONCEPT_CHECK_SLOT_TYPES[idx]  # type: ignore[return-value]


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _validate_mcq_payload(data: dict[str, Any]) -> ConceptCheckPack | None:
    data = _normalize_mcq_llm_payload(data)
    question = str(data.get("question") or "").strip()
    options = [
        str(o).strip()
        for o in (data.get("options") or [])
        if str(o).strip()
    ]
    correct = str(data.get("correct_answer") or "").strip()
    explanation = str(data.get("explanation") or "").strip()
    if len(question) < 12 or is_descriptive_stem(question):
        return None
    if len(options) < 3 or len(options) > 5:
        return None
    if not correct or correct not in options:
        return None
    return {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation": explanation or correct,
        "type": "mcq",
        "source": "ai",
    }


def _validate_fill_in_payload(data: dict[str, Any]) -> ConceptCheckPack | None:
    question = str(data.get("question") or "").strip()
    correct = str(data.get("correct_answer") or "").strip()
    explanation = str(data.get("explanation") or "").strip()
    if not has_blank_marker(question):
        if correct and correct not in question:
            question = f"{question.rstrip('.!?')} _____?"
        else:
            question = re.sub(
                BLANK_MARKER_RE,
                "_____",
                question,
                count=1,
            )
            if not has_blank_marker(question):
                question = f"Complete: {question.rstrip('.!?')} _____?"
    if len(question) < 12 or is_descriptive_stem(question):
        return None
    if not correct or len(correct.split()) > 6:
        return None
    if not is_strong_fill_in_answer(correct):
        return None
    return {
        "question": question if question.endswith("?") else f"{question}?",
        "options": [],
        "correct_answer": correct,
        "explanation": explanation or correct,
        "type": "fill_in_blank",
        "source": "ai",
    }


_OPTION_LETTER_RE = re.compile(r"^[A-Da-d]$")
_OPTION_PREFIX_RE = re.compile(r"^[A-Da-d][\).\:\-]\s*(.+)$")


def _clean_mcq_options(raw_options: list[Any]) -> list[str]:
    options: list[str] = []
    for item in raw_options or []:
        text = str(item).strip()
        if not text:
            continue
        match = _OPTION_PREFIX_RE.match(text)
        options.append(match.group(1).strip() if match else text)
    return options


def _resolve_mcq_correct_option_text(correct: str, options: list[str]) -> str | None:
    """Map LLM keys like 'B' or case variants to the exact option string."""
    if not correct or not options:
        return None
    if _OPTION_LETTER_RE.match(correct):
        idx = ord(correct.upper()) - ord("A")
        if 0 <= idx < len(options):
            return options[idx]
    lowered = {normalize_answer_text(o): o for o in options}
    key = normalize_answer_text(correct)
    if key in lowered:
        return lowered[key]
    for opt in options:
        opt_key = normalize_answer_text(opt)
        if key in opt_key or opt_key in key:
            return opt
    return None


def _normalize_mcq_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize common LLM MCQ shapes before strict validation."""
    out = dict(data)
    options = _clean_mcq_options(list(data.get("options") or []))
    out["options"] = options
    correct = str(data.get("correct_answer") or "").strip()
    resolved = _resolve_mcq_correct_option_text(correct, options)
    if resolved:
        out["correct_answer"] = resolved
    return out


def _generic_mcq_distractors(concept: str, exclude: set[str], count: int) -> list[str]:
    c = (concept or "this topic").strip()
    pool = [
        f"This was not part of the {c} explained in the lesson.",
        f"The lesson did not describe this as part of {c}.",
        "This applies to a different topic entirely.",
        "This contradicts what was shown on the board.",
    ]
    out: list[str] = []
    for item in pool:
        if item not in exclude and len(out) < count:
            out.append(item)
    while len(out) < count:
        out.append(f"None of the above relates to {c}.")
    return out[:count]


_PICK_ONE_STEM_RE = re.compile(
    r"(?i)\b(which statement|which of these|which is correct|which is true|"
    r"according to the lesson, which)\b"
)
_COUNT_STEM_RE = re.compile(r"(?i)\bhow many\b")


def _is_numeric_count_mcq(question: str, options: list[str]) -> bool:
    if not _COUNT_STEM_RE.search(question):
        return False
    return all(re.fullmatch(r"\d+", o.strip()) for o in options)


def _is_short_label_option(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and len(t.split()) <= 2 and len(t) < 28


def _options_matching_taught_facts(options: list[str], facts: list[str]) -> int:
    hits = 0
    for opt in options:
        opt_low = opt.lower().strip()
        for fact in facts:
            fact_low = fact.lower().strip()
            if opt_low == fact_low or opt_low in fact_low or fact_low in opt_low:
                hits += 1
                break
    return hits


def is_quality_mcq_pack(
    pack: dict[str, Any],
    taught_ctx: dict[str, Any] | None = None,
) -> bool:
    """Reject MCQs where multiple options could be correct or options are bare labels."""
    question = str(pack.get("question") or "").strip()
    options = [str(o).strip() for o in (pack.get("options") or []) if str(o).strip()]
    correct = str(pack.get("correct_answer") or "").strip()
    if len(options) < 3 or correct not in options:
        return False

    if _is_numeric_count_mcq(question, options):
        return True

    short_opts = sum(1 for o in options if _is_short_label_option(o))
    if short_opts >= 2:
        return False
    if _PICK_ONE_STEM_RE.search(question) and any(
        _is_short_label_option(o) for o in options
    ):
        return False

    facts: list[str] = []
    if taught_ctx:
        facts = [
            str(f).strip()
            for f in list(taught_ctx.get("teaching_facts") or [])
            + list(taught_ctx.get("taught_points") or [])
            + list(taught_ctx.get("steps") or [])
            if str(f).strip()
        ]
    if facts and _PICK_ONE_STEM_RE.search(question):
        if _options_matching_taught_facts(options, facts) > 1:
            return False

    return True


def _grounded_llm_fallback(
    *,
    concept: str,
    question_index: int,
    required_type: ConceptCheckQuestionType,
    taught_ctx: dict[str, Any],
    focus_fact: str,
    archetype: str,
) -> ConceptCheckPack | None:
    """Lesson-grounded fallback only — never generic meta templates."""
    if focus_fact:
        ruled = build_rule_based_pack_from_focus(
            focus_fact=focus_fact,
            archetype=archetype,
            question_type=required_type,
            concept=concept,
            index=question_index,
            taught_ctx=taught_ctx,
        )
        if ruled is not None and pack_matches_taught(
            ruled, taught_ctx, required_type=required_type, focus_fact=focus_fact
        ):
            return ruled

    if required_type == "mcq":
        taught_pack = _fallback_mcq_from_taught_context(
            concept, question_index, taught_ctx
        )
        if taught_pack is not None and pack_matches_taught(
            taught_pack, taught_ctx, required_type="mcq"
        ):
            return taught_pack
        return None

    if focus_fact:
        ruled = build_rule_based_pack_from_focus(
            focus_fact=focus_fact,
            archetype=archetype,
            question_type=required_type,
            concept=concept,
            index=question_index,
            taught_ctx=taught_ctx,
        )
        if ruled is not None:
            return ruled
    return None


def _facts_from_taught_context(taught_ctx: dict[str, Any]) -> list[str]:
    from app.services.handlers.teaching_transcript_service import (
        is_meta_instruction_text,
    )

    facts: list[str] = []
    seen: set[str] = set()
    for item in list(taught_ctx.get("teaching_facts") or []) + list(
        taught_ctx.get("steps") or []
    ) + list(taught_ctx.get("taught_points") or []):
        text = str(item).strip()
        if not text or is_meta_instruction_text(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(text)
    if facts:
        return facts
    excerpt = str(taught_ctx.get("lesson_excerpt") or "").strip()
    if not excerpt:
        return []
    for sent in re.split(r"(?<=[.!?])\s+", excerpt):
        text = sent.strip()
        if not text or is_meta_instruction_text(text):
            continue
        if 12 <= len(text) <= 180 and 2 <= len(text.split()) <= 24:
            key = text.lower()
            if key not in seen:
                seen.add(key)
                facts.append(text)
        if len(facts) >= 8:
            break
    return facts


def _facts_are_short_parallel_labels(facts: list[str]) -> bool:
    if len(facts) < 2:
        return False
    return all(len(f.split()) <= 3 and len(f) < 40 for f in facts)


def _count_label_for_facts(facts: list[str], concept: str) -> str:
    blob = f"{concept} {' '.join(facts)}".lower()
    if re.search(r"(?i)\b(characteristic|trait|feature|property|grow|reproduce|respir)\w*\b", blob):
        return "characteristics"
    if re.search(r"(?i)\b(step|stage|phase)\w*\b", blob):
        return "steps"
    return "key ideas"


def _count_mcq_from_taught(
    concept: str,
    step_count: int,
    facts: list[str],
    index: int,
) -> ConceptCheckPack:
    c = (concept or "this topic").strip()
    label = _count_label_for_facts(facts, c)
    correct = str(step_count)
    pool = [
        str(n)
        for n in range(1, max(step_count + 4, 6))
        if str(n) != correct
    ]
    random.shuffle(pool)
    distractors = pool[:3]
    options = [correct, *distractors]
    random.shuffle(options)
    stems = [
        f"How many {label} about {c} did we learn in this lesson?",
        f"According to the lesson, how many {label} of {c} were shown on the board?",
    ]
    question = stems[index % len(stems)]
    return {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation": f"The lesson showed {step_count} {label}.",
        "type": "mcq",
        "source": "taught_context",
    }


def _order_mcq_from_taught(
    concept: str,
    facts: list[str],
    index: int,
) -> ConceptCheckPack:
    c = (concept or "this process").strip()
    variants = [
        (0, f"According to the lesson, which comes first in {c}?"),
        (-1, f"According to the lesson, which comes last in {c}?"),
    ]
    pos, question = variants[index % len(variants)]
    correct = facts[pos]
    wrong = [f for f in facts if f != correct]
    distractors = wrong[:3]
    if len(distractors) < 3:
        exclude = {correct, *distractors}
        distractors.extend(_generic_mcq_distractors(c, exclude, 3 - len(distractors)))
    options = [correct, *distractors[:3]]
    random.shuffle(options)
    return {
        "question": question,
        "options": options,
        "correct_answer": correct,
        "explanation": correct,
        "type": "mcq",
        "source": "taught_context",
    }


def _fact_to_statement(fact: str, concept: str) -> str:
    f = fact.strip().rstrip(".")
    if len(f.split()) >= 4:
        return f if f.endswith(".") else f"{f}."
    c = (concept or "living things").strip()
    low = f.lower()
    if low.startswith(("they ", "it ", "living ", "all ")):
        return f[0].upper() + f[1:] + ("." if not f.endswith(".") else "")
    return f"{c.capitalize()} show {low}."


def _false_statement_distractors(concept: str, facts: list[str]) -> list[str]:
    c = (concept or "this topic").strip()
    fact_blob = " ".join(facts).lower()
    pool = [
        f"{c.capitalize()} never change or grow over time.",
        f"{c.capitalize()} do not need energy from their environment.",
        f"The lesson said {c.lower()} cannot respond to their surroundings.",
        f"Only non-living objects were described as {c.lower()} in the lesson.",
        f"{c.capitalize()} were described as unable to reproduce.",
    ]
    out: list[str] = []
    for stmt in pool:
        stmt_low = stmt.lower()
        if any(w in stmt_low for w in fact_blob.split() if len(w) > 4):
            continue
        if stmt not in out:
            out.append(stmt)
    while len(out) < 3:
        out.append(f"This was not taught about {c} in the lesson.")
    return out[:3]


def _statement_mcq_from_taught(
    concept: str,
    facts: list[str],
    index: int,
) -> ConceptCheckPack:
    c = (concept or "this concept").strip()
    fact = facts[index % len(facts)]
    correct = _fact_to_statement(fact, c)
    distractors = _false_statement_distractors(c, facts)
    options = [correct, *distractors[:3]]
    random.shuffle(options)
    return {
        "question": f"According to the lesson, which statement about {c} is correct?",
        "options": options,
        "correct_answer": correct,
        "explanation": correct,
        "type": "mcq",
        "source": "taught_context",
    }


def _fallback_mcq_from_taught_context(
    concept: str,
    index: int,
    taught_ctx: dict[str, Any],
) -> ConceptCheckPack | None:
    """Build a lesson-grounded MCQ with exactly one defensible correct option."""
    facts = _facts_from_taught_context(taught_ctx)
    if not facts:
        return None

    c = (concept or "this concept").strip()
    step_count = int(taught_ctx.get("step_count") or len(facts))
    rep = str(taught_ctx.get("representation") or "").lower()

    if _facts_are_short_parallel_labels(facts) and step_count >= 2:
        return _count_mcq_from_taught(c, step_count, facts, index)

    if rep in ("process", "cycle", "timeline", "flow") and step_count >= 2:
        return _order_mcq_from_taught(c, facts, index)

    if step_count >= 2 and all(len(f.split()) <= 4 for f in facts):
        pack = _order_mcq_from_taught(c, facts, index)
        if is_quality_mcq_pack(pack, taught_ctx):
            return pack

    pack = _statement_mcq_from_taught(c, facts, index)
    if is_quality_mcq_pack(pack, taught_ctx):
        return pack

    if step_count >= 2:
        return _count_mcq_from_taught(c, step_count, facts, index)

    return None


def _fallback_mcq(concept: str, index: int) -> ConceptCheckPack:
    c = (concept or "this concept").strip()
    stems = [
        f"Which statement best describes {c}?",
        f"Which of these is true about {c}?",
    ]
    stem = stems[min(index, len(stems) - 1)]
    correct = f"It is a key idea taught about {c}."
    options = [
        correct,
        f"It is unrelated to {c}.",
        f"It contradicts what we learned about {c}.",
        "None of the above apply.",
    ]
    random.shuffle(options)
    return {
        "question": stem,
        "options": options,
        "correct_answer": correct,
        "explanation": correct,
        "type": "mcq",
        "source": "template",
    }


def _fallback_fill_in(concept: str) -> ConceptCheckPack:
    c = (concept or "this concept").strip()
    correct = c.split()[0] if c else "answer"
    return {
        "question": f"The lesson focused on the concept of _____.",
        "options": [],
        "correct_answer": correct,
        "explanation": f"The concept was {c}.",
        "type": "fill_in_blank",
        "source": "template",
    }


def _pack_from_bank_row(
    row: Any,
    *,
    concept: str,
) -> ConceptCheckPack:
    qtype = infer_bank_question_type(row)
    options = list(getattr(row, "options", None) or [])
    question = str(getattr(row, "question_text", "") or "").strip()
    correct = str(getattr(row, "correct_answer", "") or "").strip()
    if qtype == "mcq" and correct and options:
        from app.services.handlers.concept_check_question_types import (
            resolve_mcq_correct_option,
        )

        resolved = resolve_mcq_correct_option(correct, options)
        if resolved:
            correct = resolved
    explanation = str(getattr(row, "explanation", "") or "").strip()
    return {
        "question": question,
        "options": options if qtype == "mcq" else [],
        "correct_answer": correct,
        "explanation": explanation or correct,
        "type": qtype,
        "source": "db",
        "concept": concept,
        "bank_id": str(getattr(row, "id", "") or ""),
    }


async def _db_difficulty_for_session(session: Session) -> tuple[str, str | dict]:
    zone = int(getattr(session, "current_zone", 1) or 1)
    if zone <= 2:
        return "easy", {"$in": ["basic"]}
    return "hard", {"$in": ["hard"]}


async def _pick_from_bank(
    ctx: HandlerContext,
    session: Session,
    *,
    concept: str,
    required_type: ConceptCheckQuestionType,
    taught_ctx: dict[str, Any] | None = None,
    quiz_stage: str = "concept_check",
) -> ConceptCheckPack | None:
    from app.models.identification.student_profiles import StudentProfile

    topic_question_repository = TopicQuestionRepository()
    _, difficulty_filter = await _db_difficulty_for_session(session)
    _difficulty_label, db_difficulty_level = await _db_difficulty_for_session(session)

    used_set = {
        str(x) for x in (getattr(session, "used_question_ids", None) or []) if x
    }

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
        if getattr(q, "quiz_stage", None) == quiz_stage
    ]
    # Difficulty-scoped fetch may have excluded medium/hard authored rows while
    # still returning unrelated bank rows — re-fetch all difficulties for stage.
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
            if getattr(q, "quiz_stage", None) == quiz_stage
        ]
    db_raw = staged

    strict = [
        q
        for q in db_raw
        if infer_bank_question_type(q) == required_type
        and _question_difficulty_matches(
            getattr(q, "difficulty_level", None),
            difficulty_filter,
        )
    ]
    loose = [
        q
        for q in db_raw
        if infer_bank_question_type(q) == required_type
    ]
    pool = strict if strict else loose

    unused = [
        q
        for q in pool
        if str(q.id) not in used_set
        and _bank_question_is_usable(q.question_text)
    ]
    if not unused:
        return None

    ranked = list(unused[:10])
    user_input = (getattr(session, "last_question", None) or concept or "").strip()
    if user_input:
        try:
            query_embedding = get_embedding(user_input[:1000])
            ranked = _rank_by_similarity(query_embedding, unused, get_embedding)
            if not ranked:
                ranked = list(unused[:10])
        except Exception:  # noqa: BLE001
            ranked = list(unused[:10])

    candidates = ranked[: min(len(ranked), 12)]
    # Prefer stable authored order over shuffle so slot 1/2 stay predictable.
    # Still shuffle only when many candidates and no quiz_stage filter? Keep
    # shuffle for variety among same-type extras, but prefer create order first.
    candidates.sort(
        key=lambda row: (
            getattr(row, "created_at", None) is None,
            getattr(row, "created_at", None) or datetime.min,
            str(getattr(row, "id", "")),
        )
    )
    for row in candidates:
        pack = _pack_from_bank_row(row, concept=concept)
        q = str(pack.get("question") or "").strip()
        if not q or not _bank_question_is_usable(q):
            continue
        # Authored bank rows are first priority — do not apply AI quality/grounding
        # gates that reject valid 2-option MCQs or teacher stems.
        if required_type == "mcq":
            options = [str(o).strip() for o in (pack.get("options") or []) if str(o).strip()]
            correct = str(pack.get("correct_answer") or "").strip()
            if len(options) < 2 or correct not in options:
                continue
        elif required_type == "fill_in_blank":
            if not str(pack.get("correct_answer") or "").strip():
                continue
            if not has_blank_marker(q):
                continue
        return pack
    return None


async def _generate_llm_pack(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    *,
    concept: str,
    required_type: ConceptCheckQuestionType,
    question_index: int,
) -> ConceptCheckPack:
    from app.models.identification.student_profiles import StudentProfile

    taught_ctx = await build_concept_quiz_taught_context(session_id, session)
    taught_block = format_transcript_taught_block(taught_ctx)
    taught_count = effective_taught_item_count(taught_ctx)
    focus_fact, focus_key = pick_focus_fact(
        taught_ctx,
        used_fact_keys=used_fact_keys(session, scope="concept"),
        question_index=question_index,
    )
    archetype = archetype_for_slot(required_type, question_index)
    focus_block = ""
    if focus_fact:
        focus_block = build_focus_assignment_block(
            concept=concept,
            focus_fact=focus_fact,
            archetype=archetype,
            question_type=required_type,
            taught_count=taught_count,
            topic_anchor=str(taught_ctx.get("topic_anchor") or ""),
        )

    last_qs = list(getattr(session, "last_questions", None) or [])
    last_block = ""
    if last_qs:
        last_block = (
            "\n\nDo NOT repeat these recent questions:\n"
            + "\n".join(f"- {x[:300]}" for x in last_qs[-5:])
        )

    if required_type == "mcq":
        type_rules = (
            "Generate ONE multiple-choice question with exactly 4 options.\n"
            "Return JSON only:\n"
            '{"question":"...","options":["full option A text","full option B text",'
            '"full option C text","full option D text"],'
            '"correct_answer":"full option B text","explanation":"..."}\n'
            "Rules: one clear stem about the focus fact only; each option must be a "
            "complete factual sentence (at least 4 words — never single-word labels); "
            "exactly one correct option; distractors must be clearly false; "
            "correct_answer must exactly match one options[] string.\n"
            "Do NOT ask about the lesson's main topic, what the teacher said, "
            "warm-up questions, or any meta-commentary — only subject facts from "
            "the board lesson."
        )

        def validator(data: dict[str, Any]) -> ConceptCheckPack | None:
            pack = _validate_mcq_payload(data)
            if pack and not is_quality_mcq_pack(pack, taught_ctx):
                return None
            if pack and not pack_matches_taught(
                pack, taught_ctx, required_type="mcq", focus_fact=focus_fact
            ):
                return None
            return pack

        def fallback() -> ConceptCheckPack:
            grounded = _grounded_llm_fallback(
                concept=concept,
                question_index=question_index,
                required_type=required_type,
                taught_ctx=taught_ctx,
                focus_fact=focus_fact,
                archetype=archetype,
            )
            if grounded is not None:
                logger.warning(
                    "[CONCEPT_CHECK] LLM MCQ failed; transcript-grounded fallback "
                    "concept=%s index=%s",
                    concept,
                    question_index,
                )
                return grounded
            logger.error(
                "[CONCEPT_CHECK] LLM MCQ failed; no grounded fallback "
                "concept=%s index=%s",
                concept,
                question_index,
            )
            return _fallback_mcq(concept, question_index)
    else:
        type_rules = (
            "Generate ONE fill-in-the-blank question.\n"
            "Return JSON only:\n"
            '{"question":"... _____ ...","correct_answer":"short phrase","explanation":"..."}\n'
            "Rules: include _____ in the question; answer is 1-4 words taken from the "
            "focus fact; no essay prompts.\n"
            "The blank MUST hide an IMPORTANT taught subject term from the focus fact "
            "(a key concept word: process, trait, organ, stage, scientific term).\n"
            "NEVER blank pronouns or filler words "
            "(themselves, himself, their, things, own, something, it, they, care).\n"
            "After filling the blank, the sentence must state a clear lesson fact.\n"
            "Do NOT ask about the lesson's main topic, what the teacher said, "
            "or any meta-commentary — only subject facts from the board lesson."
        )

        def validator(data: dict[str, Any]) -> ConceptCheckPack | None:
            pack = _validate_fill_in_payload(data)
            if pack and not pack_matches_taught(
                pack, taught_ctx, required_type="fill_in_blank", focus_fact=focus_fact
            ):
                return None
            return pack

        def fallback() -> ConceptCheckPack:
            grounded = _grounded_llm_fallback(
                concept=concept,
                question_index=question_index,
                required_type=required_type,
                taught_ctx=taught_ctx,
                focus_fact=focus_fact,
                archetype=archetype,
            )
            if grounded is not None:
                return grounded
            return _fallback_fill_in(concept)

    prompt = (
        f'Create a concept-check question ONLY about "{concept}".\n'
        f"{type_rules}\n"
    )
    if focus_block:
        prompt += f"\n{focus_block}\n"
    elif taught_block:
        prompt += (
            "Use ONLY the board lesson below. Ask about one specific fact from it. "
            "Do NOT ask about the main topic, teacher comments, or how the lesson works.\n"
        )
    else:
        prompt += "Use ONLY the lesson content below. Do not invent facts.\n"
    prompt += last_block

    # Narrow RAG context so the model cannot wander into unrelated curriculum notes.
    board_facts = taught_fact_strings(taught_ctx)
    if focus_fact:
        other = [f for f in board_facts if f.strip().lower() != focus_fact.strip().lower()][
            :6
        ]
        context = (
            "FOCUS FACT (authoritative source for the question and correct_answer):\n"
            f"{focus_fact}\n"
        )
        if other:
            context += (
                "\nOTHER BOARD FACTS (use only to invent FALSE distractors — "
                "do not ask about these):\n"
                + "\n".join(f"- {f}" for f in other)
            )
    else:
        context = taught_block or "No lesson content recorded for this concept."
        if taught_block:
            prompt += f"\nLESSON CONTENT:\n{taught_block}\n"

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
    boundary = _rag_prompt_boundary_kwargs(session, topic)

    # Prefer grounded fallback immediately when we have a focus fact but no usable
    # board context for free-form generation — keeps production deterministic.
    if focus_fact and not (taught_block or board_facts):
        pack = fallback()
        pack["concept"] = concept
        if focus_key:
            pack["_focus_fact_key"] = focus_key
        return pack

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
            data = _parse_json_object(raw)
            if data:
                pack = validator(data)
                if pack:
                    pack["concept"] = concept
                    pack["source"] = "ai"
                    if focus_key:
                        pack["_focus_fact_key"] = focus_key
                    return pack
            logger.warning(
                "[CONCEPT_CHECK] LLM output invalid concept=%s type=%s attempt=%s raw=%s",
                concept,
                required_type,
                attempt,
                (raw or "")[:240],
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[CONCEPT_CHECK] LLM generation failed concept=%s type=%s attempt=%s",
                concept,
                required_type,
                attempt,
            )

    pack = fallback()
    pack["concept"] = concept
    if focus_key:
        pack["_focus_fact_key"] = focus_key
    return pack


async def _record_question_usage(
    session: Session,
    pack: ConceptCheckPack,
) -> None:
    used_ids = list(getattr(session, "used_question_ids", None) or [])
    bank_id = str(pack.get("bank_id") or "").strip()
    if bank_id:
        if bank_id not in used_ids:
            used_ids.append(bank_id)
    else:
        q_hash = hash(str(pack.get("question") or "").strip().lower())
        ai_key = f"ai:{q_hash}"
        if ai_key not in used_ids:
            used_ids.append(ai_key)
    session.used_question_ids = used_ids
    last_qs = list(getattr(session, "last_questions", None) or [])
    q_text = str(pack.get("question") or "").strip()
    if q_text:
        session.last_questions = (last_qs + [q_text])[-5:]


async def load_concept_check_question(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    index: int,
) -> ConceptCheckPack:
    """Load one structured concept-check question for the given slot index."""
    concept = (getattr(session, "current_concept", None) or "").strip()
    if not concept:
        raise ValueError("Concept check requires current_concept on session")

    required = required_type_for_slot(index)
    taught_ctx = await build_concept_quiz_taught_context(session_id, session)
    pack = await _pick_from_bank(
        ctx,
        session,
        concept=concept,
        required_type=required,
        taught_ctx=taught_ctx,
    )
    if pack is None:
        pack = await _generate_llm_pack(
            ctx,
            session,
            session_id,
            topic,
            concept=concept,
            required_type=required,
            question_index=index,
        )

    q = str(pack.get("question") or "").strip()
    # Prefer authored Question Bank rows as-is. Grounding replacement is only for
    # AI / template packs so teachers' staged questions are never discarded.
    if str(pack.get("source") or "") != "db" and (
        is_broad_quiz_stem(q)
        or is_meta_quiz_question(q)
        or not pack_matches_taught(pack, taught_ctx, required_type=required)
    ):
        focus_fact, fk = pick_focus_fact(
            taught_ctx,
            used_fact_keys=used_fact_keys(session, scope="concept"),
            question_index=index,
        )
        grounded = _grounded_llm_fallback(
            concept=concept,
            question_index=index,
            required_type=required,
            taught_ctx=taught_ctx,
            focus_fact=focus_fact,
            archetype=archetype_for_slot(required, index),
        )
        if grounded is not None:
            logger.warning(
                "[CONCEPT_CHECK] replaced ungrounded question index=%s concept=%s",
                index,
                concept,
            )
            pack = grounded
            if fk:
                pack["_focus_fact_key"] = fk

    focus_key = str(pack.pop("_focus_fact_key", "") or "").strip()
    if focus_key:
        record_used_fact(session, focus_key, scope="concept")

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
        "[CONCEPT_CHECK] loaded index=%s type=%s source=%s concept=%s",
        index,
        pack.get("type"),
        pack.get("source"),
        concept,
    )
    return pack


def apply_concept_check_pack_to_session(session: Session, pack: ConceptCheckPack, index: int) -> None:
    qtype = str(pack.get("type") or "fill_in_blank")
    options = list(pack.get("options") or [])
    question = str(pack.get("question") or "")[:5000]
    if has_blank_marker(question):
        qtype = "fill_in_blank"
        options = []
    session.current_question = question
    answer = str(pack.get("correct_answer") or pack.get("explanation") or "").strip()
    session.current_concept_question_answer = answer[:5000] if answer else None
    session.current_concept_question_type = (
        qtype if qtype in ("mcq", "fill_in_blank") else "fill_in_blank"
    )
    session.current_concept_question_options = (
        [str(o).strip() for o in options if str(o).strip()][:10]
        if qtype == "mcq"
        else []
    )
    session.concept_question_index = max(0, min(index, CONCEPT_QUESTIONS_PER_CONCEPT - 1))
    session.concept_question_followup = False
    session.concept_question_clarifying = False
    session.concept_question_pending_advance = False


def clear_concept_check_question_fields(session: Session) -> None:
    session.current_concept_question_answer = None
    session.current_concept_question_type = None
    session.current_concept_question_options = []
    session.current_question = None
