"""Single authority for "this concept's VTSE timeline has finished playing."

Concept Check and later teaching stages may advance only when
``can_complete_vtse_stage`` returns true. A missing later stage is not
completion.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.services.pedagogy import vtse_opening_claim

logger = logging.getLogger(__name__)

ACTION_VTSE_STAGE_DONE = "concept_vtse_stage_done"


def vtse_timeline_requires_playback(session: Any) -> bool:
    """True when the session holds a real VTSE timeline that must play."""
    cache = getattr(session, "zone1_timeline_cache", None)
    if not isinstance(cache, dict):
        return False
    if not str(cache.get("timeline_id") or "").strip():
        return False
    beats = cache.get("beats") or []
    return isinstance(beats, list) and len(beats) > 0


def cached_timeline(session: Any) -> Optional[dict[str, Any]]:
    cache = getattr(session, "zone1_timeline_cache", None)
    if not vtse_timeline_requires_playback(session):
        return None
    return cache


def last_beat_index(cache: dict[str, Any]) -> int:
    beats = list(cache.get("beats") or [])
    indexes: list[int] = []
    for i, beat in enumerate(beats):
        if isinstance(beat, dict) and isinstance(beat.get("index"), int):
            indexes.append(int(beat["index"]))
        else:
            indexes.append(i)
    if not indexes:
        return -1
    return max(indexes)


def _concepts_match(left: Any, right: Any) -> bool:
    lk = " ".join(str(left or "").strip().lower().split())
    rk = " ".join(str(right or "").strip().lower().split())
    return bool(lk and rk and lk == rk)


def _cursor(session: Any) -> int:
    raw = getattr(session, "zone1_last_completed_beat_index", None)
    if isinstance(raw, bool) or raw is None:
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def stage_still_on_vtse(session: Any) -> bool:
    seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
    idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
    return 0 <= idx < len(seq) and str(seq[idx]) == "vtse"


def is_vtse_stage_done_action(action: Optional[str]) -> bool:
    if not action:
        return False
    head = str(action).split("|", 1)[0].strip().lower()
    return head == ACTION_VTSE_STAGE_DONE


def parse_vtse_stage_done_identity(user_input: Optional[str]) -> Optional[dict[str, Any]]:
    """Parse identity from ``__action:concept_vtse_stage_done|{json}``."""
    raw = (user_input or "").strip()
    lower = raw.lower()
    prefix = f"__action:{ACTION_VTSE_STAGE_DONE}"
    if not lower.startswith(prefix):
        return None
    rest = raw[len(prefix) :]
    if rest.startswith("|"):
        rest = rest[1:]
    rest = rest.strip()
    if not rest:
        return None
    try:
        parsed = json.loads(rest)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def can_complete_vtse_stage(
    session: Any,
    expected_timeline_identity: Optional[dict[str, Any]],
) -> tuple[bool, str]:
    """
    Durable playback completion for the active concept's VTSE timeline.

    Returns ``(ok, reason)``. On failure the caller must leave
    ``concept_teaching_await_vtse_done`` true and must not arm Concept Check.
    """
    if bool(getattr(session, "concept_questions_active", False)):
        return False, "already_active"
    if not bool(getattr(session, "concept_teaching_await_vtse_done", False)):
        return False, "not_awaiting"
    if not stage_still_on_vtse(session):
        return False, "stage_consumed"
    if vtse_opening_claim.opening_status(session) != vtse_opening_claim.VTSE_OPENING_READY:
        return False, "opening_not_ready"
    if not vtse_opening_claim.opening_applies_to_current_concept(session):
        return False, "concept_index_mismatch"

    identity = dict(expected_timeline_identity or {})
    expected_tid = str(identity.get("timeline_id") or "").strip()
    cache = cached_timeline(session)
    if not expected_tid and cache is not None:
        expected_tid = str(cache.get("timeline_id") or "").strip()
        identity["timeline_id"] = expected_tid
    if not expected_tid:
        logger.warning(
            "[VTSE_STAGE] missing timeline id cache_present=%s",
            isinstance(getattr(session, "zone1_timeline_cache", None), dict),
        )
        return False, "missing_timeline_identity"

    raw_idx = identity.get("concept_index")
    if raw_idx is not None:
        try:
            if int(raw_idx) != vtse_opening_claim.concept_index(session):
                return False, "concept_index_mismatch"
        except (TypeError, ValueError):
            return False, "concept_index_mismatch"

    cache = cached_timeline(session)
    if cache is None:
        return False, "no_timeline"

    board_concept = getattr(session, "zone1_board_concept_id", None)
    current_concept = getattr(session, "current_concept", None)
    if not _concepts_match(board_concept, current_concept):
        return False, "timeline_concept_mismatch"

    expected_concept = identity.get("concept_id")
    if expected_concept is not None and str(expected_concept).strip():
        if not _concepts_match(expected_concept, current_concept):
            return False, "concept_id_mismatch"
        if not _concepts_match(expected_concept, board_concept):
            return False, "concept_id_mismatch"

    cached_tid = str(cache.get("timeline_id") or "").strip()
    if cached_tid != expected_tid:
        return False, "timeline_mismatch"

    if bool(getattr(session, "flow_checkpoint_pending", False)):
        return False, "checkpoint_pending"

    last = last_beat_index(cache)
    if last < 0:
        return False, "beat_incomplete"
    cursor_ok = _cursor(session) == last
    claimed = identity.get("final_beat_index")
    claimed_ok = False
    if claimed is not None:
        try:
            claimed_ok = int(claimed) == last
        except (TypeError, ValueError):
            claimed_ok = False
    # The beat cursor is client-written and often lags the finished timeline.
    # A stage_done for this exact timeline may name the final beat. An open
    # checkpoint was already rejected above, so this cannot arm mid-pause.
    if not cursor_ok and not claimed_ok:
        return False, "beat_incomplete"
    if claimed_ok and _cursor(session) != last:
        session.zone1_last_completed_beat_index = last
    return True, "ok"


def bind_active_vtse_timeline(
    session: Any, identity: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Use this concept's cached timeline when the client omitted timeline_id."""
    bound = dict(identity or {})
    if str(bound.get("timeline_id") or "").strip():
        return bound
    cache = cached_timeline(session)
    if cache is None:
        return bound
    bound["timeline_id"] = str(cache.get("timeline_id") or "")
    return bound


def reject_vtse_stage_done(
    reason: str,
    *,
    session_id: Any = None,
    concept_index: Any = None,
    timeline_id: Any = None,
) -> dict[str, Any]:
    logger.warning(
        "[VTSE_STAGE] rejected session_id=%s concept_index=%s timeline_id=%s reason=%s",
        session_id,
        concept_index,
        timeline_id,
        reason,
    )
    try:
        from app.services.pedagogy.teaching_runtime_metrics import incr

        incr("vtse_stage_done_rejected")
    except Exception:
        pass
    return {
        "type": "noop",
        "vtse_stage_complete": False,
        "reason": reason,
    }


def apply_scoped_beat_cursor(
    session: Any,
    proposed: int,
    *,
    timeline_id: Optional[str],
    allow_final: bool,
) -> bool:
    """
    Advance ``zone1_last_completed_beat_index`` only for the active timeline.

    Monotonic. ``allow_final=False`` refuses a write that would land on the
    last beat (checkpoint inference must not count as playback completion).
    Returns True when the cursor changes.
    """
    cache = cached_timeline(session)
    if cache is None:
        return False
    active = str(cache.get("timeline_id") or "").strip()
    supplied = str(timeline_id or "").strip()
    # Omitted id means the only active timeline. A different id must not move it.
    if supplied and supplied != active:
        return False
    try:
        proposed_i = int(proposed)
    except (TypeError, ValueError):
        return False
    if proposed_i < 0:
        return False
    last = last_beat_index(cache)
    if last < 0 or proposed_i > last:
        return False
    if not allow_final and proposed_i >= last:
        return False
    current = _cursor(session)
    if proposed_i <= current:
        return False
    session.zone1_last_completed_beat_index = proposed_i
    return True
