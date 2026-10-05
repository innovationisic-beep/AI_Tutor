"""
Story Hook runtime — walks a validated plan one step per turn.

All authority lives here: the backend decides which step is next, whether the
student may type, and when the stage is finished. The frontend only renders what
it is handed and reports that narration finished.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.language.tutor_language_policy import (
    ENGLISH,
    HINGLISH,
    TutorLanguageMode,
    static_text,
)
from app.services.story_hook.plan_schema import (
    WRITING_MODE_LEGACY,
    StoryHookPlan,
    StoryHookStep,
    StoryHookWritingMode,
    plan_from_stored,
    resolve_card_written,
)
from app.services.story_hook.planner import (
    build_outline,
    plan_story_hook,
    respond_to_story_hook_answer,
)

logger = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_PLAYING = "playing"
STATUS_WAITING = "waiting_for_student"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

MAX_QA_LOG = 4


def visual_path(concept_id: Any, asset_key: str) -> str:
    """API-relative media path; the client prefixes its API base."""
    return f"/curriculum/concepts/{concept_id}/story-hook/visuals/{asset_key}"


def is_awaiting_student(session: Any) -> bool:
    return str(getattr(session, "story_hook_status", "") or "") == STATUS_WAITING


def reset_runtime(session: Any) -> None:
    """Clear plan state so a new concept re-plans from scratch."""
    session.story_hook_for_index = -1
    session.story_hook_plan = None
    session.story_hook_step_index = 0
    session.story_hook_status = STATUS_IDLE
    session.story_hook_pending_question = None
    session.story_hook_qa = []
    session.story_hook_language = ENGLISH


async def ensure_plan(
    session: Any,
    *,
    concept: Any,
    hook: Any,
    concept_label: str,
    language_mode: TutorLanguageMode,
    continuity: Optional[dict] = None,
) -> Optional[StoryHookPlan]:
    """
    Return the plan for the current concept, generating it on first use.

    Re-plans when the concept index moved or the student switched language
    mid-lesson, so a language change takes effect on the next eligible stage
    without restarting the session.
    """
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    stored = plan_from_stored(getattr(session, "story_hook_plan", None))
    raw_for = getattr(session, "story_hook_for_index", -1)
    same_concept = (-1 if raw_for is None else int(raw_for)) == idx
    same_language = (
        str(getattr(session, "story_hook_language", "") or "") == language_mode
    )
    started = int(getattr(session, "story_hook_step_index", 0) or 0) > 0
    # A language switch takes effect on the next eligible stage, never mid-story.
    if stored is not None and same_concept and (same_language or started):
        return stored

    plan = await plan_story_hook(
        concept=concept,
        hook=hook,
        concept_label=concept_label,
        language_mode=language_mode,
        continuity=continuity,
    )
    session.story_hook_for_index = idx
    session.story_hook_plan = plan.model_dump()
    session.story_hook_step_index = 0
    session.story_hook_status = STATUS_PLAYING
    session.story_hook_pending_question = None
    session.story_hook_qa = []
    session.story_hook_language = language_mode
    return plan


def current_step(session: Any, plan: StoryHookPlan) -> Optional[StoryHookStep]:
    index = int(getattr(session, "story_hook_step_index", 0) or 0)
    if index < 0 or index >= len(plan.steps):
        return None
    return plan.steps[index]


def build_response(
    *,
    text: str,
    kind: str,
    index: int,
    total: int,
    last: bool,
    concept_id: Any = None,
    asset_key: str = "",
    hook_title: str = "",
    current_concept: str = "",
    flow_state: str = "",
    note: str = "",
    writes: Optional[List[Dict[str, Any]]] = None,
    writing_mode: StoryHookWritingMode = WRITING_MODE_LEGACY,
) -> Dict[str, Any]:
    """
    Build the tutor response for one Story Hook turn.

    ``message`` is always spoken ``text`` (TTS). Card body uses optional
    ``writes`` / ``note`` when ``writing_mode`` is notes; legacy plans keep
    body == text.
    """
    spoken = text.strip()
    note_clean = (note or "").strip()
    writes_clean: List[Dict[str, Any]] = []
    for w in writes or []:
        if not isinstance(w, dict):
            continue
        try:
            idx = int(w.get("sentence_index"))
        except (TypeError, ValueError):
            continue
        wtext = str(w.get("text") or "").strip()
        if not wtext:
            continue
        writes_clean.append({"sentence_index": idx, "text": wtext})
    step_for_write = StoryHookStep(
        type="narration",
        text=spoken,
        note=note_clean,
        asset_key=asset_key or "",
        writes=writes_clean,  # type: ignore[arg-type]
    )
    written = resolve_card_written(
        step_for_write,
        writing_mode=writing_mode,
        kind=kind,
    )
    card: Dict[str, Any] = {
        "kind": "story_hook",
        "heading": "STORY HOOK",
        "title": hook_title or "Story Hook",
        "body": written,
        "description": written,
        "note": note_clean,
        "writing_mode": writing_mode,
        "spoken_text": spoken,
    }
    if writes_clean:
        card["writes"] = writes_clean
    if kind == "visual" and asset_key and concept_id is not None:
        card["image_path"] = visual_path(concept_id, asset_key)
        card["image_alt"] = written or spoken or asset_key

    step_meta: Dict[str, Any] = {
        "kind": kind,
        "index": index,
        "total": total,
        "awaiting": kind == "question",
        "last": bool(last),
        "writing_mode": writing_mode,
        "note": note_clean,
    }
    if writes_clean:
        step_meta["writes"] = writes_clean

    return {
        "type": "concept_story_hook",
        "message": spoken,
        "story_hook_card": card,
        "visual": {"type": "concept_story_hook", "card": card},
        "story_hook_step": step_meta,
        "current_concept": current_concept,
        "flow_state": flow_state,
    }


def step_response(
    session: Any,
    plan: StoryHookPlan,
    step: StoryHookStep,
    *,
    concept_id: Any,
    hook_title: str,
    current_concept: str,
    flow_state: str,
) -> Dict[str, Any]:
    """Response for the plan step at the session's current index."""
    index = int(getattr(session, "story_hook_step_index", 0) or 0)
    total = len(plan.steps)
    mode: StoryHookWritingMode = getattr(plan, "writing_mode", None) or WRITING_MODE_LEGACY
    writes_payload = [
        {"sentence_index": int(w.sentence_index), "text": str(w.text or "")}
        for w in (getattr(step, "writes", None) or [])
        if str(getattr(w, "text", "") or "").strip()
    ]
    return build_response(
        text=step.text,
        kind=step.type,
        index=index,
        total=total,
        last=index >= total - 1,
        concept_id=concept_id,
        asset_key=step.asset_key,
        hook_title=hook_title,
        current_concept=current_concept,
        flow_state=flow_state,
        note=step.note,
        writes=writes_payload,
        writing_mode=mode,
    )


def mark_emitted(session: Any, step: StoryHookStep) -> None:
    """Record what the student is now looking at, before their next turn."""
    if step.type == "question":
        session.story_hook_status = STATUS_WAITING
        session.story_hook_pending_question = step.text[:400]
        return
    session.story_hook_status = STATUS_PLAYING
    session.story_hook_pending_question = None


def advance_step(session: Any) -> None:
    session.story_hook_step_index = (
        int(getattr(session, "story_hook_step_index", 0) or 0) + 1
    )


def plan_exhausted(session: Any, plan: StoryHookPlan) -> bool:
    return int(getattr(session, "story_hook_step_index", 0) or 0) >= len(plan.steps)


def mark_done(session: Any) -> None:
    session.story_hook_status = STATUS_DONE
    session.story_hook_pending_question = None


async def build_answer_reply(
    session: Any,
    *,
    student_answer: str,
    concept: Any,
    concept_label: str,
    language_mode: TutorLanguageMode,
) -> str:
    """
    Fresh LLM reply to a Story Hook answer, with a neutral template fallback.

    Never scored: the exchange is logged for continuity only.
    """
    question = str(getattr(session, "story_hook_pending_question", "") or "").strip()
    answer = student_answer.strip()

    reply = await respond_to_story_hook_answer(
        question=question,
        student_answer=answer,
        concept_label=concept_label,
        outline=build_outline(concept, concept_label=concept_label),
        language_mode=language_mode,
    )
    if not reply:
        reply = static_text(
            "story_hook_answer_ack",
            language_mode,
            english="Good — hold on to that thought. Let's keep going.",
        )

    log: List[Dict[str, Any]] = list(getattr(session, "story_hook_qa", None) or [])
    log.append({"question": question, "answer": answer[:600], "reply": reply})
    session.story_hook_qa = log[-MAX_QA_LOG:]
    session.story_hook_pending_question = None
    session.story_hook_status = STATUS_PLAYING
    return reply


def resolve_language_label(raw: Any) -> TutorLanguageMode:
    """Normalize a persisted plan language back to a tutor language mode."""
    return HINGLISH if str(raw or "").strip().lower() == HINGLISH else ENGLISH
