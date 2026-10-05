"""
Flow checkpoint runtime — temporary clarifications during flow_vertical_process playback.

Does not create timelines, VTSE boards, or new lessons. Orchestration-only.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from beanie.odm.fields import PydanticObjectId

from app.repositories.event_repository import EventRepository
from app.services.handlers.explanation_handler import (
    _micro_build_rag_context,
    generate_tutor_rag_reply,
)

if TYPE_CHECKING:
    from app.models.curriculum.topics import Topic
    from app.models.learning.sessions import Session
    from app.models.teacher_topic import TeacherTopic
    from app.services.handlers.context import HandlerContext

logger = logging.getLogger(__name__)

_CLOSING = "Hope that clears your confusion."


def _log(tag: str, payload: dict[str, Any] | None = None, *, session: Any = None) -> None:
    extra = ""
    if session is not None:
        cache = getattr(session, "zone1_timeline_cache", None)
        tid = ""
        if isinstance(cache, dict):
            tid = str(cache.get("timeline_id") or "")
        extra = (
            f" session_id={getattr(session, 'id', None)}"
            f" concept_index={getattr(session, 'current_concept_index', None)}"
            f" timeline_id={tid}"
        )
    logger.info("[%s]%s %s", tag, extra, payload or {})


async def _persist_fields(session: Any, fields: dict[str, Any]) -> None:
    """Narrow $set when the session is a stored document; full save for test doubles."""
    sid = getattr(session, "id", None)
    if sid is not None:
        try:
            from datetime import datetime

            from app.models.learning.sessions import Session

            await Session.get_pymongo_collection().update_one(
                {"_id": sid},
                {"$set": {**fields, "updated_at": datetime.utcnow()}},
            )
            return
        except Exception:
            logger.exception("[FLOW_CHECKPOINT] narrow_persist_failed")
    save = getattr(session, "save", None)
    if save is not None:
        await save()


def _action_name_and_tail(raw_question: str) -> tuple[str, str]:
    """Return ``(action, tail)`` from ``__action:name|tail`` without lowercasing the tail."""
    text = (raw_question or "").strip()
    lower = text.lower()
    body = text[len("__action:") :] if lower.startswith("__action:") else text
    lower_body = body.lower()
    if "|" not in lower_body:
        return lower_body.strip(), ""
    name, _, _rest = lower_body.partition("|")
    tail = body[len(name) + 1 :]
    return name.strip(), tail.strip()


def _active_timeline_id(session: Any) -> str:
    cache = getattr(session, "zone1_timeline_cache", None)
    if isinstance(cache, dict):
        return str(cache.get("timeline_id") or "").strip()
    return ""


def _parse_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_flow_checkpoint_pause_request(
    raw_question: str,
) -> tuple[list[str], int | None, str | None]:
    """Labels plus optional timeline id and completed-node count.

    Accepts the legacy list payload and
    ``{"labels","timeline_id","completed_node_count"}``.
    """
    _name, tail = _action_name_and_tail(raw_question)
    if not tail:
        return [], None, None
    try:
        parsed = json.loads(tail)
    except json.JSONDecodeError:
        return [], None, None
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()], None, None
    if isinstance(parsed, dict):
        raw_labels = parsed.get("labels")
        if not isinstance(raw_labels, list):
            raw_labels = parsed.get("step_labels")
        labels = (
            [str(x).strip() for x in raw_labels if str(x).strip()]
            if isinstance(raw_labels, list)
            else []
        )
        tid = str(parsed.get("timeline_id") or "").strip() or None
        return labels, _parse_count(parsed.get("completed_node_count")), tid
    return [], None, None


def parse_flow_checkpoint_pause_labels(raw_question: str) -> list[str]:
    """Extract step labels from a pause action (list or object payload)."""
    labels, _count, _tid = parse_flow_checkpoint_pause_request(raw_question)
    return labels


def parse_flow_checkpoint_question_request(raw_question: str) -> dict[str, Any] | None:
    """Identity payload for ``__action:flow_checkpoint_question|{...}``."""
    name, tail = _action_name_and_tail(raw_question)
    if name != "flow_checkpoint_question":
        return None
    data: dict[str, Any] = {}
    if tail:
        try:
            parsed = json.loads(tail)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    return {
        "timeline_id": str(data.get("timeline_id") or "").strip(),
        "completed_node_count": _parse_count(data.get("completed_node_count")),
        "text": str(data.get("text") or "").strip(),
    }


def stale_flow_checkpoint_question() -> dict[str, Any]:
    """Closed or foreign checkpoint. Never a teachback score."""
    return {
        "type": "flow_checkpoint_clarification",
        "outcome": "stale",
        "message": "",
    }


async def handle_flow_checkpoint_pause(
    session: Session,
    *,
    labels: list[str],
    completed_node_count: int | None = None,
    timeline_id: str | None = None,
) -> dict[str, Any]:
    expected = str(timeline_id or "").strip()
    active = _active_timeline_id(session)
    if expected and active and expected != active:
        _log(
            "FLOW_CHECKPOINT_PAUSE_REJECTED",
            {"reason": "timeline_mismatch", "expected": expected, "active": active},
            session=session,
        )
        return {"type": "noop"}
    _log("FLOW_CHECKPOINT_PAUSED", {"labels": labels}, session=session)
    session.flow_checkpoint_pending = True
    session.flow_checkpoint_resolved = False
    session.flow_checkpoint_step_labels = labels
    if completed_node_count is not None:
        session.flow_completed_node_count = int(completed_node_count)
    if labels:
        fc_idx = int(session.flow_checkpoint_index or 0) + 1
        session.flow_checkpoint_index = fc_idx
        inferred_beat = max(0, fc_idx * 2 - 1)
        # Inference is not playback completion. Never land on the final beat.
        from app.services.pedagogy.vtse_stage_completion import (
            apply_scoped_beat_cursor,
            cached_timeline,
        )

        cache = cached_timeline(session)
        if cache is not None:
            apply_scoped_beat_cursor(
                session,
                inferred_beat,
                timeline_id=str(cache.get("timeline_id") or ""),
                allow_final=False,
            )
    await _persist_fields(
        session,
        {
            "flow_checkpoint_pending": True,
            "flow_checkpoint_resolved": False,
            "flow_checkpoint_step_labels": list(labels),
            **(
                {"flow_completed_node_count": int(completed_node_count)}
                if completed_node_count is not None
                else {}
            ),
            **(
                {"flow_checkpoint_index": int(session.flow_checkpoint_index or 0)}
                if labels
                else {}
            ),
            **(
                {
                    "zone1_last_completed_beat_index": getattr(
                        session, "zone1_last_completed_beat_index", None
                    )
                }
                if labels and cache is not None
                else {}
            ),
        },
    )
    return {"type": "noop"}


async def handle_flow_checkpoint_continue(
    session: Session,
    *,
    expected_timeline_id: str | None = None,
) -> dict[str, Any]:
    """
    Clear checkpoint ownership so the FE may resume VTSE playback / stage-done.

    Returns an explicit ack (not a generic noop) so the client can await
    confirmation before resuming the timeline.
    """
    _log("FLOW_CHECKPOINT_CONTINUE", {}, session=session)
    expected = str(expected_timeline_id or "").strip()
    if expected:
        cache = getattr(session, "zone1_timeline_cache", None)
        active = (
            str(cache.get("timeline_id") or "").strip()
            if isinstance(cache, dict)
            else ""
        )
        if active and expected != active:
            pending = bool(getattr(session, "flow_checkpoint_pending", False))
            _log(
                "FLOW_CHECKPOINT_CONTINUE_REJECTED",
                {"reason": "timeline_mismatch", "expected": expected, "active": active},
                session=session,
            )
            try:
                from app.services.pedagogy.teaching_runtime_metrics import incr

                incr("flow_checkpoint_continue_rejected")
            except Exception:
                pass
            return {
                "type": "flow_checkpoint_continue_ack",
                "outcome": "timeline_mismatch",
                "flow_checkpoint_pending": 1 if pending else 0,
            }
    was_pending = bool(getattr(session, "flow_checkpoint_pending", False))
    session.flow_checkpoint_pending = False
    session.flow_checkpoint_resolved = True
    await _persist_fields(
        session,
        {
            "flow_checkpoint_pending": False,
            "flow_checkpoint_resolved": True,
        },
    )
    outcome = "accepted" if was_pending else "already_cleared"
    _log("FLOW_CHECKPOINT_RESUME", {"path": "continue", "outcome": outcome}, session=session)
    return {
        "type": "flow_checkpoint_continue_ack",
        "outcome": outcome,
        "flow_checkpoint_pending": 0,
    }


async def handle_flow_checkpoint_question(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    student_text: str,
) -> dict[str, Any]:
    _log("FLOW_CHECKPOINT_QUESTION", {"question_len": len(student_text or "")}, session=session)
    labels = list(getattr(session, "flow_checkpoint_step_labels", None) or [])
    labels_text = ", ".join(labels) if labels else "recent steps"
    cc = (getattr(session, "current_concept", None) or "").strip() or "this process"
    rag_question = (
        f"The student is learning the flow process for \"{cc}\". "
        f"They just completed these steps: {labels_text}.\n"
        f"Their confusion: {student_text.strip()}\n\n"
        "Give ONE focused clarification in 2-4 short sentences. "
        "Do NOT start a new lesson, introduce new concepts, or ask follow-up questions. "
        f"End with exactly: {_CLOSING}"
    )

    rag_service, context, student_profile, topic_for_prompt = await _micro_build_rag_context(
        ctx, session, student_id, topic
    )
    answer = await generate_tutor_rag_reply(
        session,
        session_id,
        student_id,
        rag_question,
        session.topic_id,
        "UNKNOWN",
        "explaining",
        topic_for_prompt,
        rag_service,
        context,
        student_profile,
        EventRepository(),
        persist_session_qa=False,
    )
    msg = (answer or "").strip()
    if _CLOSING.lower() not in msg.lower():
        msg = f"{msg.rstrip()}\n\n{_CLOSING}"

    # Keep checkpoint open until the student explicitly continues.
    session.flow_checkpoint_pending = True
    session.flow_checkpoint_resolved = False
    await _persist_fields(
        session,
        {
            "flow_checkpoint_pending": True,
            "flow_checkpoint_resolved": False,
        },
    )
    _log("FLOW_CHECKPOINT_CLARIFICATION_SENT", {"length": len(msg)}, session=session)
    return {"type": "flow_checkpoint_clarification", "message": msg}


async def handle_flow_checkpoint_question_action(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic,
    raw_question: str,
) -> dict[str, Any]:
    """Clarification for one open checkpoint, or a stale rejection.

    A mismatch must not be graded as a cluster teachback answer.
    """
    parsed = parse_flow_checkpoint_question_request(raw_question) or {}
    text = str(parsed.get("text") or "").strip()
    expected = str(parsed.get("timeline_id") or "").strip()
    count = parsed.get("completed_node_count")
    active = _active_timeline_id(session)
    pending = bool(getattr(session, "flow_checkpoint_pending", False))
    open_count = _parse_count(getattr(session, "flow_completed_node_count", None))
    matched = (
        pending
        and bool(text)
        and bool(expected)
        and bool(active)
        and expected == active
        and count is not None
        and open_count is not None
        and count == open_count
    )
    if not matched:
        _log(
            "FLOW_CHECKPOINT_QUESTION_REJECTED",
            {
                "reason": "stale",
                "pending": pending,
                "expected": expected,
                "active": active,
                "completed_node_count": count,
                "open_count": open_count,
            },
            session=session,
        )
        return stale_flow_checkpoint_question()
    return await handle_flow_checkpoint_question(
        ctx, session, session_id, student_id, topic, text
    )


def parse_flow_checkpoint_continue_timeline(raw_question: str) -> str | None:
    text = raw_question or ""
    marker = "flow_checkpoint_continue|"
    idx = text.lower().find(marker)
    if idx < 0:
        return None
    return text[idx + len(marker) :].strip() or None


async def maybe_dispatch_flow_checkpoint(
    ctx: HandlerContext,
    session: Session,
    session_id: PydanticObjectId,
    student_id: PydanticObjectId,
    topic: Topic | TeacherTopic | None,
    raw_question: str,
) -> dict[str, Any] | None:
    """Handle pause, identified question, and continue. None for every other request."""
    name, _tail = _action_name_and_tail(raw_question)
    if name == "flow_checkpoint_pause" or name.startswith("flow_checkpoint_pause"):
        labels, count, tid = parse_flow_checkpoint_pause_request(raw_question)
        return await handle_flow_checkpoint_pause(
            session,
            labels=labels,
            completed_node_count=count,
            timeline_id=tid,
        )
    if name == "flow_checkpoint_continue" or name.startswith("flow_checkpoint_continue"):
        return await handle_flow_checkpoint_continue(
            session,
            expected_timeline_id=parse_flow_checkpoint_continue_timeline(raw_question),
        )
    if name == "flow_checkpoint_question" or name.startswith("flow_checkpoint_question"):
        if topic is None:
            return stale_flow_checkpoint_question()
        return await handle_flow_checkpoint_question_action(
            ctx, session, session_id, student_id, topic, raw_question
        )
    return None

