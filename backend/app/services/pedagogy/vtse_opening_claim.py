"""
Atomic ownership for Zone-1 VTSE micro-teaching opening.

Prevents concurrent idle / stale Visual Teaching asks from generating
duplicate teacher_micro_teaching_opening timelines for one concept.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pymongo import ReturnDocument

from app.models.learning.sessions import Session

logger = logging.getLogger(__name__)

VTSE_OPENING_UNCLAIMED = "unclaimed"
VTSE_OPENING_STARTING = "starting"
VTSE_OPENING_READY = "ready"
VTSE_OPENING_FAILED = "failed"

FLOW_VTSE_OPENING = "concept_vtse_opening"

VtseOpeningOutcome = Literal[
    "claimed",
    "already_starting",
    "already_started",
    "stale",
]


def reset_vtse_opening(session: Session) -> None:
    """Reset opening ownership when a new concept teaching snapshot is frozen."""
    session.concept_vtse_opening_status = VTSE_OPENING_UNCLAIMED
    session.concept_vtse_opening_for_index = -1


def opening_status(session: Any) -> str:
    raw = str(getattr(session, "concept_vtse_opening_status", "") or "").strip().lower()
    if raw in (
        VTSE_OPENING_UNCLAIMED,
        VTSE_OPENING_STARTING,
        VTSE_OPENING_READY,
        VTSE_OPENING_FAILED,
    ):
        return raw
    return VTSE_OPENING_UNCLAIMED


def opening_for_index(session: Any) -> int:
    raw = getattr(session, "concept_vtse_opening_for_index", -1)
    try:
        return int(raw) if raw is not None else -1
    except (TypeError, ValueError):
        return -1


def concept_index(session: Any) -> int:
    try:
        return int(getattr(session, "current_concept_index", 0) or 0)
    except (TypeError, ValueError):
        return 0


def opening_applies_to_current_concept(session: Any) -> bool:
    return opening_for_index(session) == concept_index(session)


def is_opening_claimed_or_ready(session: Any) -> bool:
    """True when this concept's VTSE opening is starting or already delivered."""
    if not opening_applies_to_current_concept(session):
        return False
    return opening_status(session) in (VTSE_OPENING_STARTING, VTSE_OPENING_READY)


def is_opening_in_progress(session: Any) -> bool:
    if not opening_applies_to_current_concept(session):
        return False
    return opening_status(session) == VTSE_OPENING_STARTING


def is_opening_ready(session: Any) -> bool:
    if not opening_applies_to_current_concept(session):
        return False
    return opening_status(session) == VTSE_OPENING_READY


def vtse_opening_ack(
    *,
    outcome: VtseOpeningOutcome,
    concept_index: int,
    flow_state: str,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": "vtse_opening_ack",
        "outcome": outcome,
        "concept_index": int(concept_index),
        "status": status or opening_status_from_outcome(outcome),
        "flow_state": flow_state,
    }


def opening_status_from_outcome(outcome: VtseOpeningOutcome) -> str:
    if outcome == "already_started":
        return VTSE_OPENING_READY
    if outcome in ("already_starting", "claimed"):
        return VTSE_OPENING_STARTING
    return VTSE_OPENING_UNCLAIMED


def _session_oid(session_id: Any) -> Optional[PydanticObjectId]:
    if session_id is None:
        return None
    if isinstance(session_id, PydanticObjectId):
        return session_id
    try:
        return PydanticObjectId(str(session_id))
    except Exception:  # noqa: BLE001
        return None


def hydrate_opening_fields(session: Session, fields: Dict[str, Any]) -> None:
    if "concept_vtse_opening_status" in fields:
        session.concept_vtse_opening_status = str(
            fields["concept_vtse_opening_status"] or VTSE_OPENING_UNCLAIMED
        )
    if "concept_vtse_opening_for_index" in fields:
        try:
            session.concept_vtse_opening_for_index = int(
                fields["concept_vtse_opening_for_index"]
            )
        except (TypeError, ValueError):
            session.concept_vtse_opening_for_index = -1
    if "flow_state" in fields and fields["flow_state"]:
        session.flow_state = str(fields["flow_state"])


async def atomic_claim_vtse_opening(
    session_id: Any,
    *,
    concept_index: int,
    set_flow_opening: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Claim VTSE opening for ``concept_index``.

    Succeeds only when this concept has not already claimed starting/ready.
    Failed openings are retryable. Returns the BEFORE document on success.
    """
    oid = _session_oid(session_id)
    if oid is None:
        return None
    idx = int(concept_index)
    filt: Dict[str, Any] = {
        "_id": oid,
        "current_concept_index": idx,
        "$or": [
            # Never claimed for this concept (legacy / new concept).
            {"concept_vtse_opening_for_index": {"$ne": idx}},
            {"concept_vtse_opening_for_index": {"$exists": False}},
            {
                "concept_vtse_opening_for_index": idx,
                "concept_vtse_opening_status": {
                    "$in": [
                        VTSE_OPENING_UNCLAIMED,
                        VTSE_OPENING_FAILED,
                        None,
                        "",
                    ]
                },
            },
            {
                "concept_vtse_opening_for_index": idx,
                "concept_vtse_opening_status": {"$exists": False},
            },
        ],
    }
    set_fields: Dict[str, Any] = {
        "concept_vtse_opening_status": VTSE_OPENING_STARTING,
        "concept_vtse_opening_for_index": idx,
        "updated_at": datetime.utcnow(),
    }
    if set_flow_opening:
        set_fields["flow_state"] = FLOW_VTSE_OPENING
    coll = Session.get_pymongo_collection()
    before = await coll.find_one_and_update(
        filt,
        {"$set": set_fields},
        return_document=ReturnDocument.BEFORE,
    )
    return before


async def atomic_mark_vtse_opening_ready(
    session_id: Any,
    *,
    concept_index: int,
) -> bool:
    """Mark opening delivered. Only transitions from starting for this concept."""
    oid = _session_oid(session_id)
    if oid is None:
        return False
    idx = int(concept_index)
    coll = Session.get_pymongo_collection()
    result = await coll.update_one(
        {
            "_id": oid,
            "concept_vtse_opening_for_index": idx,
            "concept_vtse_opening_status": VTSE_OPENING_STARTING,
        },
        {
            "$set": {
                "concept_vtse_opening_status": VTSE_OPENING_READY,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return bool(getattr(result, "modified_count", 0))


async def atomic_mark_vtse_opening_failed(
    session_id: Any,
    *,
    concept_index: int,
) -> bool:
    """
    Mark claim failed/retryable. Releases FLOW_VTSE_OPENING back to idle so a
    later legitimate request can re-claim. Does not clear ready openings.
    """
    oid = _session_oid(session_id)
    if oid is None:
        return False
    idx = int(concept_index)
    coll = Session.get_pymongo_collection()
    result = await coll.update_one(
        {
            "_id": oid,
            "concept_vtse_opening_for_index": idx,
            "concept_vtse_opening_status": VTSE_OPENING_STARTING,
        },
        {
            "$set": {
                "concept_vtse_opening_status": VTSE_OPENING_FAILED,
                "flow_state": "idle",
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return bool(getattr(result, "modified_count", 0))


def acknowledge_existing_opening(session: Any) -> Dict[str, Any]:
    """Deterministic ack when opening is already starting or ready."""
    idx = concept_index(session)
    flow = str(getattr(session, "flow_state", "idle") or "idle")
    if is_opening_ready(session):
        return vtse_opening_ack(
            outcome="already_started",
            concept_index=idx,
            flow_state=flow,
            status=VTSE_OPENING_READY,
        )
    return vtse_opening_ack(
        outcome="already_starting",
        concept_index=idx,
        flow_state=flow if flow != "idle" else FLOW_VTSE_OPENING,
        status=VTSE_OPENING_STARTING,
    )
