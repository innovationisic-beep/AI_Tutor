"""
Zone 0 handler — standalone async functions extracted from SessionService.

All logic is IDENTICAL to the original private methods in session_service.py.
`self.*` references have been replaced with the HandlerContext `ctx` parameter
or with local helpers defined below.  SessionService is never imported here.

Public API (called from session_service.py):
    zone0_idle_dispatch(ctx, session, session_id, student_id, topic, phase)
    zone0_skip(ctx, session, session_id, topic)
    zone0_emit_anchor(ctx, session, session_id, student_id, topic)
    zone0_emit_prereq_or_skip(..., post_anchor_reply=None)
    zone0_handle_prereq_answer(ctx, session, session_id, student_id, answer, topic)
    zone0_emit_curiosity(..., prior_anchor_reply=None)
    zone0_after_curiosity_answer(ctx, session, session_id, student_id, student_reply, topic)
    zone0_complete_to_zone1(ctx, session, session_id, student_id, topic, student_thought)

Helper exported for session_service diagnostic flow:
    diagnostic_filtered_prereq_ids(session, topic_repository) -> list[str]
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, List, Optional

import httpx
from beanie.odm.fields import PydanticObjectId

from app.core.config import DEEPSEEK_THINKING_DISABLED, Settings
from app.models.curriculum.prerequisite_graph import PrerequisiteGraph
from app.models.curriculum.topics import Topic
from app.models.learning.mastery_records import MasteryRecord, normalize_concept
from app.models.teacher_topic import TeacherTopic
from app.services.pedagogy.teacher_voice import (
    TEACHER_WARMTH_RULES,
    build_continuity_card,
    zone0_close_paragraph,
)
from app.services.language.tutor_language_policy import (
    ENGLISH,
    STAGE_ZONE0_CURIOSITY,
    STAGE_ZONE0_PREREQ,
    TutorLanguageMode,
    apply_language_to_system_prompt,
    resolve_mode_for_session,
    resolve_mode_from_profile,
    static_text,
)
from app.services.speech_note_dual import (
    PROSE_DUAL_RULES as _PROSE_DUAL_RULES,
    WRITING_MODE_LEGACY,
    WRITING_MODE_NOTES,
    notes_payload as _zone0_notes_fields,
    parse_prose_dual as _parse_zone0_prose_dual,
    parse_prose_dual_full as _parse_zone0_prose_dual_full,
)

if TYPE_CHECKING:
    from app.models.learning.sessions import Session
    from app.repositories.topic_repository import TopicRepository
    from app.services.handlers.context import HandlerContext

# ─────────────────────────────────────────────────────────────────────────────
# Internal constants
# ─────────────────────────────────────────────────────────────────────────────

_DIAG_MAX_PREREQ = 3  # Maximum prerequisite topics examined per session

_ZONE0_SYSTEM = (
    "You are a warm, conversational AI companion — you are NOT teaching right now. "
    "Your only role is to prepare the student's mind before learning begins. "
    "STRICT RULES you must obey:\n"
    "- NEVER explain any concept, term, or subject matter.\n"
    "- NEVER give examples of the topic being studied.\n"
    "- NEVER define anything.\n"
    "- Keep every response SHORT — follow the exact sentence limit given.\n"
    "- Write naturally and warmly, like a real person talking to a student.\n"
    "- If asked to write a question, write ONLY the question — no intro, no label."
)

# Re-export for tests that import dual helpers from this module.
MAX_ZONE0_NOTE_CHARS = 280


def _zone0_system(
    mode: TutorLanguageMode = ENGLISH,
    *,
    stage: str = STAGE_ZONE0_CURIOSITY,
) -> str:
    """Zone 0 system prompt with the stage language policy applied."""
    return apply_language_to_system_prompt(_ZONE0_SYSTEM, stage=stage, mode=mode)


def _zone0_anchor_reply_is_trivial(text: str) -> bool:
    """Short confirmations — skip a separate mirror LLM before the next Zone 0 beat."""
    s = (text or "").strip().lower().rstrip(".!?")
    if not s or s.startswith("__action:"):
        return True
    trivial = frozenset(
        {
            "ok",
            "okay",
            "yes",
            "yep",
            "yeah",
            "yup",
            "sure",
            "k",
            "kk",
            "go",
            "start",
            "begin",
            "mhm",
            "mmhm",
            "cool",
            "got it",
            "alright",
            "all right",
            "fine",
            "ready",
        }
    )
    return s in trivial


def zone0_student_text_confirms_ready(text: str) -> bool:
    """True when the student is explicitly starting the lesson (typed or button)."""
    t = (text or "").strip().lower()
    if t == "__action:zone0_ready":
        return True
    if t.startswith("__action:"):
        return False
    markers = (
        "i'm ready",
        "im ready",
        "lets go",
        "let's go",
        "ready to start",
        "ready to begin",
        "start the lesson",
        "let's begin",
        "lets begin",
        "yes let's",
        "yes lets",
        "go ahead",
        "okay let's go",
        "ok let's go",
        "start now",
    )
    return any(m in t for m in markers)


def _zone0_signals_uncertainty(text: str) -> bool:
    """Student is unsure — completion copy must not praise a 'great answer'."""
    t = (text or "").strip().lower()
    if not t or t.startswith("__action:"):
        return False
    needles = (
        "don't know",
        "dont know",
        "do not know",
        "idk",
        "dunno",
        "no idea",
        "not sure",
        "unsure",
        "hard to say",
        "haven't thought",
        "havent thought",
        "can't think",
        "cant think",
        "no clue",
        "beats me",
        "wish i knew",
        "tough question",
    )
    return any(n in t for n in needles)


async def _zone0_reflect_anchor_reply(
    student_reply: str,
    topic_name: str,
    *,
    mode: TutorLanguageMode = ENGLISH,
) -> tuple[str, str, str, list]:
    """
    Warm mirror after the anchor question.

    Returns (spoken, note, writing_mode, writes). Note/writes may be used on a
    standalone zone0_mirror turn (skip-prereq). Prereq path still uses spoken
    only when folding.
    """
    user_msg = (
        f"The student was asked what they picture about \"{topic_name}\" before any "
        f"teaching. They replied:\n\"{student_reply.strip()}\"\n\n"
        "TASK: Spoken reply of ONE or at most TWO short sentences (max 45 words total).\n"
        "- Pick up something concrete they said (sunlight, garden, etc.) so they feel heard.\n"
        "- Warm, natural voice — curious friend, not a coach scoring them.\n"
        "- You may end with a soft pivot toward wondering (not a second quiz question).\n\n"
        "FORBIDDEN: defining terms, explaining the topic, giving facts, homework tone, "
        "calling their answer correct/incorrect.\n"
        "NO numbered lists. NO third sentence."
        f"{_PROSE_DUAL_RULES}"
        "Prefer a short educational board write (contrast / key observation) or empty — "
        "never praise or UI filler."
    )
    try:
        result = await _llm_call(
            user_content=user_msg,
            system_content=_zone0_system(mode),
            temperature=0.55,
        )
        return _parse_zone0_prose_dual_full(result, language=mode)
    except Exception:
        return "", "", WRITING_MODE_LEGACY, []


async def _llm_call(
    user_content: str,
    *,
    system_content: str = "You are an expert tutor.",
    temperature: float = 0.4,
    timeout: float = 60.0,
) -> Optional[str]:
    """Minimal DeepSeek chat completion — identical logic to SessionService._deepseek_chat_completion."""
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


async def _get_topic_or_teacher_topic_impl(
    topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
) -> Topic | TeacherTopic | None:
    """Resolve a topic ID to either a Topic or a TeacherTopic document."""
    t = await topic_repository.get_by_id(topic_id)
    if t is not None:
        return t
    return await TeacherTopic.get(topic_id)


def _diagnostic_concept_overlap_score(
    current_concept: str | None, prereq_key_concepts: List[str]
) -> float:
    """Score how much the current concept overlaps with prereq key concepts."""
    if not current_concept or not prereq_key_concepts:
        return 0.0
    cur_toks = set(re.findall(r"[a-z0-9]+", current_concept.lower()))
    if not cur_toks:
        return 0.0
    best = 0.0
    for kc in prereq_key_concepts:
        kt = set(re.findall(r"[a-z0-9]+", (kc or "").lower()))
        if not kt:
            continue
        inter = len(cur_toks & kt)
        if inter:
            best = max(best, float(inter) / max(len(kt), 1))
    return best


async def _diagnostic_prerequisite_edges(session: Session) -> List[PrerequisiteGraph]:
    tid = session.topic_id
    oid = session.organization_id
    edges = await PrerequisiteGraph.find(
        {"topic_id": tid, "organization_id": oid}
    ).to_list()
    if not edges:
        edges = await PrerequisiteGraph.find(
            {"topic_id": tid, "organization_id": None}
        ).to_list()
    return edges or []


# ─────────────────────────────────────────────────────────────────────────────
# Public helper — also re-used by the diagnostic flow in session_service.py
# ─────────────────────────────────────────────────────────────────────────────


async def diagnostic_filtered_prereq_ids(
    session: Session,
    topic_repository: TopicRepository,
) -> List[str]:
    """
    Return up to _DIAG_MAX_PREREQ prerequisite topic IDs, ranked by concept overlap.
    Identical logic to SessionService._diagnostic_filtered_prereq_ids.
    """
    edges = await _diagnostic_prerequisite_edges(session)
    if not edges:
        return []
    cc = normalize_concept(getattr(session, "current_concept", None))
    scored: List[tuple[float, PydanticObjectId]] = []
    for e in edges:
        pid = e.prerequisite_topic_id
        doc = await _get_topic_or_teacher_topic_impl(pid, topic_repository)
        kc_list = list(getattr(doc, "key_concepts", None) or []) if doc else []
        score = _diagnostic_concept_overlap_score(
            cc if cc else (session.key_concepts[0] if session.key_concepts else None),
            kc_list,
        )
        scored.append((score, pid))
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    ordered: List[str] = []
    seen: set[str] = set()
    for _, pid in scored:
        sid = str(pid)
        if sid in seen:
            continue
        seen.add(sid)
        ordered.append(sid)
    if not any(s > 0 for s, _ in scored):
        ordered = [str(e.prerequisite_topic_id) for e in edges]
        seen = set()
        out: List[str] = []
        for sid in ordered:
            if sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
        ordered = out
    return ordered[:_DIAG_MAX_PREREQ]


# ─────────────────────────────────────────────────────────────────────────────
# Zone 0 public handler functions
# ─────────────────────────────────────────────────────────────────────────────


async def zone0_idle_dispatch(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic,
    phase: str,
) -> dict:
    """
    Route to the correct Zone 0 micro-phase handler based on `phase`.
    Called from session_service when flow == 'idle', current_zone == 0,
    and zone0_phase != 'done'.
    """
    if phase == "anchoring":
        return await zone0_emit_anchor(ctx, session, session_id, student_id, topic)
    # After anchor, session_service advances out of anchor_wait before calling here.
    if phase == "anchor_wait":
        return {"type": "noop"}
    if phase == "prereq":
        return await zone0_emit_prereq_or_skip(ctx, session, session_id, student_id, topic)
    # curiosity_pending = mirror on board awaiting zone0_mirror_done — do NOT emit Q2 here.
    if phase == "curiosity_pending":
        return {"type": "noop"}
    if phase == "curiosity":
        return await zone0_emit_curiosity(ctx, session, session_id, student_id, topic)
    # Unrecognised / stale phase — skip Zone 0 safely.
    return await zone0_skip(ctx, session, session_id, topic)


async def zone0_skip(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    topic,
) -> dict:
    """Fast-path: mark Zone 0 done and hand off to Zone 1 immediately."""
    session.zone0_phase = "done"
    session.current_zone = 1
    session.flow_state = "idle"
    await session.save()
    return {
        "type": "feedback",
        "message": "",
        "correct": True,
        "current_concept": session.current_concept or "",
    }


async def zone0_emit_anchor(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic,
) -> dict:
    """
    Phase 1 — Curiosity anchor (Zone 0).
    One short line: a single curiosity question only (no lesson, no pep talk).
    The session then waits for student input before prereq/curiosity (see anchor_wait).
    """
    from app.models.identification.student_profiles import StudentProfile

    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    interests: list[str] = list(
        (student_profile.interests if student_profile else None) or []
    )
    student_name = (
        (student_profile.full_name or "").strip()
        if student_profile
        else ""
    )

    past_sessions = await ctx.session_repository.get_student_sessions(
        student_id, limit=5, organization_id=session.organization_id
    )
    same_topic_past = [
        s for s in past_sessions
        if str(s.topic_id) == str(session.topic_id)
        and str(s.id) != str(session.id)
    ]

    mastery_rows: list = []
    try:
        mastery_rows = await MasteryRecord.find(
            {"student_id": student_id, "topic_id": session.topic_id}
        ).to_list()
    except Exception:
        mastery_rows = []

    topic_name = topic.topic_name if topic else "this topic"
    all_concepts = list(session.key_concepts or [])
    concepts_overview = ", ".join(all_concepts[:8]) if all_concepts else topic_name

    ctx_parts: list[str] = []
    if student_name:
        ctx_parts.append(f"Student name: {student_name}")
    if interests:
        ctx_parts.append(f"Student interests: {', '.join(interests[:4])}")
    ctx_parts.append(f"Today's topic: {topic_name}")
    ctx_parts.append(f"Topic covers: {concepts_overview}")

    if same_topic_past:
        last_s = same_topic_past[0]
        sus_prev = float(getattr(last_s, "sus_score", 50.0) or 50.0)
        lc = list(getattr(last_s, "learned_concepts", None) or [])
        ctx_parts.append(
            f"Student studied this topic before. Last SUS score: {sus_prev:.0f}/100."
        )
        if lc:
            ctx_parts.append(
                "Concepts covered last time: " + ", ".join(str(c) for c in lc[:4])
            )
    else:
        ctx_parts.append("This is the student's very first session on this topic.")

    if mastery_rows:
        strong = [
            str(m.concept)
            for m in mastery_rows
            if float(getattr(m, "mastery_score", 0) or 0) >= 75 and m.concept
        ]
        weak = [
            str(m.concept)
            for m in mastery_rows
            if float(getattr(m, "mastery_score", 100) or 100) < 50 and m.concept
        ]
        if strong:
            ctx_parts.append("Previously mastered well: " + ", ".join(strong[:3]))
        if weak:
            ctx_parts.append("Previously struggled with: " + ", ".join(weak[:3]))

    history_line = (
        f"They previously studied this topic. Last SUS score: "
        f"{float(getattr(same_topic_past[0], 'sus_score', 50.0) or 50.0):.0f}/100."
        if same_topic_past
        else "This is their very first session on this topic."
    )
    name_line = f"Student name: {student_name}" if student_name else ""
    interests_line = (
        f"Student interests: {', '.join(interests[:3])}" if interests else ""
    )

    user_msg = (
        f"{name_line}\n{interests_line}\n{history_line}\n"
        f"Topic title: \"{topic_name}\".\n\n"
        "TASK — write ONE sentence only (max ~20 words).\n"
        "It must be a single curiosity question that nudges them to notice what "
        "they already think or feel about this topic — before any teaching.\n\n"
        "STRICT RULES:\n"
        "- Output ONLY that one sentence — no title, no label, no second sentence.\n"
        "- End with a question mark.\n"
        "- Do NOT greet, welcome, motivate, or hype the session.\n"
        "- Do NOT explain, define, list concepts, or give examples from the topic.\n"
        "- Do NOT mention lessons, sessions, or 'today we will'.\n"
        f"{'- You may use their first name inside the question if it fits naturally.' if student_name else ''}\n\n"
        "GOOD: When you hear \"photosynthesis\", what comes to your mind?\n"
        "BAD: Welcome! I'm excited to explore… / This topic is important because…"
    )

    anchor_text: str = ""
    try:
        result = await _llm_call(
            user_content=user_msg,
            system_content=_zone0_system(resolve_mode_from_profile(student_profile)),
            temperature=0.55,
        )
        anchor_text = (result or "").strip()
    except Exception:
        anchor_text = ""

    if not anchor_text:
        anchor_text = f'When you hear "{topic_name}", what comes to your mind?'

    # Standalone step: wait for student reply (or zone0_next) before prereq/curiosity.
    session.zone0_phase = "anchor_wait"
    session.flow_state = "idle"
    await session.save()

    return {
        "type": "zone0_anchor",
        "message": anchor_text,
    }


async def zone0_emit_prereq_or_skip(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic,
    post_anchor_reply: str | None = None,
) -> dict:
    """
    Phase 2 — Prerequisite Check.
    Asks one Socratic recall question about the most relevant prerequisite topic.
    If no prerequisite edges exist, skips directly to the curiosity phase.
    """
    from app.repositories.topic_note_repository import TopicNoteRepository
    from app.repositories.topic_question_repository import TopicQuestionRepository
    from app.repositories.video_subtitle_repository import VideoSubtitleRepository
    from app.services.rag_service import RAGService

    prereq_ids = await diagnostic_filtered_prereq_ids(session, ctx.topic_repository)

    topic_name = topic.topic_name if topic else "this topic"
    anchor_mirror = ""
    anchor_mirror_note = ""
    anchor_mirror_mode = WRITING_MODE_LEGACY
    anchor_mirror_writes: list = []
    _par = (post_anchor_reply or "").strip()
    if _par.lower().startswith("__action:"):
        _par = ""
    _par_substantive = bool(_par) and not _zone0_anchor_reply_is_trivial(_par)
    language_mode = await resolve_mode_for_session(session)
    if _par_substantive:
        (
            anchor_mirror,
            anchor_mirror_note,
            anchor_mirror_mode,
            anchor_mirror_writes,
        ) = await _zone0_reflect_anchor_reply(_par, topic_name, mode=language_mode)

    if not prereq_ids:
        session.zone0_prereq_done = True
        if _par_substantive:
            session.zone0_pending_anchor_reply = _par[:5000]
        else:
            session.zone0_pending_anchor_reply = None

        # Skip-prereq: emit standalone mirror (notes), then FE auto-advances to Q2.
        if anchor_mirror.strip():
            session.zone0_phase = "curiosity_pending"
            session.flow_state = "zone0_mirror"
            await session.save()
            out: dict = {
                "type": "zone0_mirror",
                "message": anchor_mirror.strip(),
                "flow_state": "zone0_mirror",
                "current_concept": session.current_concept or "",
            }
            if anchor_mirror_mode == WRITING_MODE_NOTES:
                out.update(
                    _zone0_notes_fields(
                        message=anchor_mirror.strip(),
                        display_text=anchor_mirror_note,
                        writes=anchor_mirror_writes,
                    )
                )
            return out

        session.zone0_phase = "curiosity"
        session.flow_state = "idle"
        await session.save()
        return await zone0_emit_curiosity(
            ctx,
            session,
            session_id,
            student_id,
            topic,
            prior_anchor_reply=_par if _par_substantive else None,
        )

    prereq_topic_id = prereq_ids[0]
    prereq_topic = await _get_topic_or_teacher_topic_impl(prereq_topic_id, ctx.topic_repository)
    prereq_name = (
        prereq_topic.topic_name if prereq_topic else "a foundational topic"
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
    notes = await rag_service.get_topic_notes(
        topic_id=prereq_topic_id,
        organization_id=session.organization_id,
        teaching_style=None,
        interest_category="general",
        difficulty_level="basic",
        current_concept=None,
        user_query=prereq_name,
        curriculum_class_id=getattr(session, "curriculum_class_id", None),
        curriculum_subject_id=getattr(session, "curriculum_subject_id", None),
    )
    key_ideas = ""
    if notes:
        snippets = []
        for n in notes[:2]:
            txt = (n.content_markdown or "").strip()
            if txt:
                first = txt.split(".")[0].strip()
                snippets.append(first[:120])
        if snippets:
            key_ideas = " Key ideas from this topic: " + ". ".join(snippets) + "."

    user_msg = (
        f"The student is about to learn '{topic.topic_name if topic else 'a new topic'}'. "
        f"They have previously studied '{prereq_name}'.{key_ideas}\n\n"
        f"TASK: Write exactly ONE short, friendly Socratic recall question that "
        f"checks whether the student remembers a key idea from '{prereq_name}'.\n"
        f"CONSTRAINTS:\n"
        f"- ONE question only — no introduction, no label, no explanation.\n"
        f"- Conversational and non-threatening (e.g. 'Do you remember...', "
        f"'Can you recall...', 'What do you think...').\n"
        f"- The question should take 5-10 seconds to answer — not an essay."
    )

    question_text = ""
    try:
        result = await _llm_call(
            user_content=user_msg,
            system_content=_zone0_system(language_mode, stage=STAGE_ZONE0_PREREQ),
            temperature=0.5,
        )
        question_text = (result or "").strip()
    except Exception:
        question_text = ""

    if not question_text:
        question_text = f"Do you remember what makes something a {prereq_name.lower()}?"

    session.zone0_prereq_question = question_text[:5000]
    session.zone0_phase = "prereq_active"
    session.flow_state = "zone0_prereq"
    await session.save()

    intro = static_text(
        "zone0_prereq_intro",
        language_mode,
        english=(
            "Before we begin, let me ask you a quick question about something "
            "we've covered before — just to warm up."
        ),
    )
    parts: list[str] = []
    if anchor_mirror:
        parts.append(anchor_mirror)
    parts.append(intro)
    parts.append(question_text)
    board_message = "\n\n".join(p for p in parts if p.strip())

    return {
        "type": "zone0_prereq",
        "message": board_message,
    }


async def zone0_handle_prereq_answer(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    answer: str,
    topic,
) -> dict:
    """
    Evaluate the student's Zone 0 prerequisite answer.
    The check is INFORMATIONAL — it never blocks progression.
    Pass or fail, the student always moves to the curiosity phase.
    """
    _raw = answer.strip()
    if not _raw or _raw == "." or _raw.lower().startswith("__action:"):
        return {"type": "noop"}

    question = (getattr(session, "zone0_prereq_question", None) or "").strip()

    feedback_prefix = ""
    if question:
        language_mode = await resolve_mode_for_session(session)
        user_msg = (
            f'The student was asked: "{question}"\n'
            f'The student answered: "{_raw}"\n\n'
            f"TASK: Spoken feedback — exactly ONE warm sentence.\n"
            f"- If the answer shows understanding → affirm it briefly and naturally.\n"
            f"- If the answer is weak or wrong → gently acknowledge their effort and "
            f"hint at the right direction in one sentence — do NOT explain the topic.\n"
            f"CONSTRAINTS:\n"
            f"- ONE spoken sentence only.\n"
            f"- Do NOT say 'correct' or 'incorrect' literally.\n"
            f"- Do NOT start teaching the concept."
            f"{_PROSE_DUAL_RULES}"
            "Prefer empty writes here; never summarize the recall question as board text."
        )
        try:
            result = await _llm_call(
                user_content=user_msg,
                system_content=_zone0_system(
                    language_mode,
                    stage=STAGE_ZONE0_PREREQ,
                ),
                temperature=0.5,
            )
            spoken, _note, _wm, _writes = _parse_zone0_prose_dual_full(
                result, language=language_mode
            )
            feedback_prefix = spoken
        except Exception:
            feedback_prefix = ""

    session.zone0_prereq_done = True
    session.zone0_prereq_question = None
    session.zone0_phase = "curiosity"
    session.flow_state = "idle"
    await session.save()

    curiosity_result = await zone0_emit_curiosity(ctx, session, session_id, student_id, topic)
    if feedback_prefix:
        curiosity_result["message"] = (
            feedback_prefix + "\n\n" + curiosity_result.get("message", "")
        )
    return curiosity_result


async def zone0_emit_curiosity(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic,
    prior_anchor_reply: str | None = None,
) -> dict:
    """
    Phase 3 — Second curiosity question (Zone 0).
    Same style as anchor: one short question only, no framing paragraph.
    Not evaluated — warms curiosity before Zone 1.
    """
    from app.models.identification.student_profiles import StudentProfile

    student_profile = await StudentProfile.find_one(
        {"organization_id": session.organization_id, "user_id": session.student_id}
    )
    interests: list[str] = list(
        (student_profile.interests if student_profile else None) or []
    )
    topic_name = topic.topic_name if topic else "this topic"
    all_concepts = list(session.key_concepts or [])
    topic_scope = ", ".join(all_concepts[:8]) if all_concepts else topic_name

    interests_hint = (
        f" Student interests: {', '.join(interests[:3])}."
        " You may lean on one lightly inside the question if it fits."
        if interests
        else ""
    )

    prior_block = ""
    _prior = (prior_anchor_reply or "").strip()
    if not _prior:
        _prior = (getattr(session, "zone0_pending_anchor_reply", None) or "").strip()
    if _prior:
        prior_block = (
            f"The student just shared this spontaneous image (do not quote it whole if long; "
            f"let the next question feel like a natural 'what if' follow-on): "
            f"\"{_prior[:400]}\"\n\n"
        )

    user_msg = (
        f"Topic title: \"{topic_name}\".\n"
        f"Related scope (names only, do not teach): {topic_scope}.{interests_hint}\n\n"
        f"{prior_block}"
        "TASK — write ONE sentence only (max ~22 words).\n"
        "It must be a single curiosity question about this topic — different angle "
        "from a generic 'what is X' (e.g. a concrete mechanism, comparison, or "
        "everyday puzzle).\n\n"
        "STRICT RULES:\n"
        "- Output ONLY that one sentence — no title, no label, no second sentence.\n"
        "- End with a question mark.\n"
        "- No emojis. No 'Before we begin', no reassurance paragraphs, no hype.\n"
        "- Do NOT explain, define, list concepts, or give the answer.\n\n"
        'GOOD: What do you think plants use from the air to make their food?\n'
        "BAD: 🤔 Before we begin… / Here's something fascinating…"
    )

    raw_question = ""
    try:
        result = await _llm_call(
            user_content=user_msg,
            system_content=_zone0_system(resolve_mode_from_profile(student_profile)),
            temperature=0.55,
        )
        raw_question = (result or "").strip()
        raw_question = raw_question.lstrip("Question:").strip().strip('"').strip("'")
    except Exception:
        raw_question = ""

    if not raw_question:
        raw_question = (
            "What do you think plants take from the air to help them make food?"
        )

    session.zone0_curiosity_question = raw_question[:5000]
    session.zone0_phase = "curiosity_wait"
    session.zone0_curiosity_shown = True
    session.zone0_pending_anchor_reply = None
    session.flow_state = "zone0_curiosity"
    await session.save()

    return {
        "type": "zone0_curiosity",
        "message": raw_question,
    }


async def _zone0_next_focus(session: Session) -> str:
    """Student-facing direction of the first teaching stage. Empty if unknown."""
    concept = None
    try:
        ids = list(getattr(session, "key_concept_ids", None) or [])
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        if 0 <= idx < len(ids):
            from app.repositories.curriculum_concept_repository import (
                CurriculumConceptRepository,
            )

            concept = await CurriculumConceptRepository().get_by_id(ids[idx])
    except Exception:  # noqa: BLE001
        concept = None
    label = str(getattr(session, "current_concept", "") or "")
    if concept is not None:
        label = str(getattr(concept, "display_name", None) or label)
    card = build_continuity_card(
        concept=concept,
        session=session,
        current_stage=None,
        concept_name=label,
        include_student_thread=False,
    )
    return str(card.get("next_focus") or "")


async def zone0_after_curiosity_answer(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    student_reply: str,
    topic,
) -> dict:
    """
    After the student answers the curiosity (Q2) question: AI-tailored reply, then
    offer the \"I'm ready\" control. Zone 1 starts only after zone0_complete_to_zone1.
    """
    raw = (student_reply or "").strip()
    if not raw or raw == ".":
        return {"type": "noop"}
    if raw.lower().startswith("__action:"):
        return {"type": "noop"}

    q = (getattr(session, "zone0_curiosity_question", None) or "").strip()
    topic_name = topic.topic_name if topic else "this topic"
    uncertain = _zone0_signals_uncertainty(raw)
    language_mode = await resolve_mode_for_session(session)
    session.zone0_student_thread = " ".join(raw.split())[:200]
    close = zone0_close_paragraph(await _zone0_next_focus(session))

    if uncertain:
        user_msg = (
            f"Topic (no full lesson yet — still a warm-up): \"{topic_name}\".\n"
            f"Curiosity question they saw: \"{q or 'a curiosity question about this topic'}\"\n"
            f"They expressed uncertainty: \"{raw[:800]}\"\n\n"
            "TASK: Spoken text — exactly TWO short paragraphs (max 95 words total).\n"
            "Paragraph 1: Normalize not knowing — these prompts are for wonder, not a test. "
            "Do NOT use empty praise like 'nice work', 'great job', or 'well done'.\n"
            f"{close}\n\n"
            "FORBIDDEN: lecturing the science, listing facts, emojis, bullet points."
            f"{_PROSE_DUAL_RULES}"
            "A good board write is a short educational takeaway from their thought — "
            "or empty writes if nothing durable belongs on the board. "
            "Never write Ready/button/UI instructions as board text.\n\n"
            f"{TEACHER_WARMTH_RULES}"
        )
    else:
        user_msg = (
            f"Topic (still pre-lesson, do not teach the concept): \"{topic_name}\".\n"
            f"Curiosity question they saw: \"{q or 'a curiosity question'}\"\n"
            f"The student replied: \"{raw[:800]}\"\n\n"
            "TASK: Spoken text — exactly TWO short paragraphs (max 95 words total).\n"
            "Paragraph 1: Respond in a specific, human way to what they wrote — "
            "reference their ideas where it fits. Do NOT use generic praise phrases like "
            "'nice work', 'great job', 'well done', or 'excellent'.\n"
            f"{close}\n\n"
            "FORBIDDEN: teaching the full answer, quiz tone, bullet lists, emojis."
            f"{_PROSE_DUAL_RULES}"
            "A good board write is a short educational takeaway — or empty writes. "
            "Never write Ready/button/UI instructions as board text.\n\n"
            f"{TEACHER_WARMTH_RULES}"
        )

    raw_llm = ""
    try:
        result = await _llm_call(
            user_content=user_msg,
            system_content=_zone0_system(language_mode),
            temperature=0.55,
        )
        raw_llm = (result or "").strip()
    except Exception:
        raw_llm = ""

    spoken, note, writing_mode, writes = _parse_zone0_prose_dual_full(
        raw_llm, language=language_mode
    )
    if not spoken:
        if uncertain:
            spoken = (
                "That's an honest answer — these questions are only meant to spark "
                "curiosity, not to grade you.\n\n"
                "When you're ready to start the topic, tap the button below and we'll "
                "take it one step at a time."
            )
        else:
            spoken = (
                "Thanks for sharing that — it helps me see where you're coming from.\n\n"
                "If you're ready to begin the lesson, tap the button below whenever you like."
            )
        writing_mode = WRITING_MODE_LEGACY
        note = ""
        writes = []

    session.zone0_phase = "curiosity_ready"
    session.flow_state = "zone0_curiosity"
    await session.save()

    out: dict = {
        "type": "zone0_curiosity",
        "message": spoken,
        "buttons": [
            {"id": "zone0_ready", "label": "I'm ready — let's go"},
        ],
        "current_concept": session.current_concept or "",
    }
    if writing_mode == WRITING_MODE_NOTES:
        out.update(
            _zone0_notes_fields(message=spoken, display_text=note, writes=writes)
        )
    return out


async def zone0_complete_to_zone1(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic,
    student_thought: str = "",
) -> dict:
    """
    Final Zone 0 handoff after the student confirms readiness (button or clear text).
    No extra LLM — the personalized beat already happened in zone0_after_curiosity_answer.
    """
    session.zone0_phase = "done"
    session.current_zone = 1
    session.flow_state = "idle"
    session.zone0_curiosity_question = None
    await session.save()

    return {
        "type": "feedback",
        "message": "",
        "correct": True,
        "current_concept": session.current_concept or "",
    }
