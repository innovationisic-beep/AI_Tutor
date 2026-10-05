"""Visual Teaching session runtime — plan freeze, beat advance, board payload."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Set, Tuple

from beanie.odm.fields import PydanticObjectId
from pymongo import ReturnDocument

from app.models.learning.sessions import Session
from app.services.visual_teaching.authored import normalize_visual_teaching
from app.services.visual_teaching.plan_schema import (
    VisualTeachingPlan,
    visual_state_at,
)
from app.services.visual_teaching.planner import plan_visual_teaching_with_retry
from app.services.visual_teaching.validate import (
    VisualTeachingPlanError,
    build_fixture_plan,
)
from app.services.storage.visual_teaching_storage import get_visual_teaching_storage

logger = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_PLAYING = "playing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

FLOW_VISUAL_TEACHING = "concept_visual_teaching"
ACTION_VISUAL_TEACHING_DONE = "visual_teaching_done"
ACTION_VISUAL_TEACHING_NEXT = "visual_teaching_next"
ACTION_VISUAL_TEACHING_SENTENCE = "visual_teaching_sentence"

AdvanceOutcome = Literal[
    "accepted",
    "already_advanced",
    "stale",
    "completed",
]


def reset_runtime(session: Session) -> None:
    session.visual_teaching_for_index = int(
        getattr(session, "concept_teaching_for_index", -1) or -1
    )
    session.visual_teaching_plan = None
    session.visual_teaching_scene_index = 0
    session.visual_teaching_beat_index = 0
    session.visual_teaching_sentence_index = -1
    session.visual_teaching_status = STATUS_IDLE
    session.visual_teaching_skipped_scenes = []


def plan_from_stored(raw: Any) -> Optional[VisualTeachingPlan]:
    if not raw:
        return None
    try:
        return VisualTeachingPlan.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def is_stage_done(session: Session) -> bool:
    status = str(getattr(session, "visual_teaching_status", "") or "")
    return status in (STATUS_DONE, STATUS_FAILED)


async def ensure_plan(
    session: Session,
    *,
    authored_snapshot: Any,
    vtse_template: Any = None,
    language: str = "en",
    concept_name: str = "",
    use_fixture: bool = False,
    continuity: Optional[dict] = None,
) -> Optional[VisualTeachingPlan]:
    existing = plan_from_stored(getattr(session, "visual_teaching_plan", None))
    status = str(getattr(session, "visual_teaching_status", "") or "")
    if existing is not None and status in (STATUS_PLAYING, STATUS_DONE):
        return existing

    pkg = normalize_visual_teaching(authored_snapshot)
    if pkg is None:
        session.visual_teaching_status = STATUS_FAILED
        return None

    plan: Optional[VisualTeachingPlan] = None
    if use_fixture:
        try:
            plan = build_fixture_plan(pkg, language=language)
        except VisualTeachingPlanError as exc:
            logger.warning("[VISUAL_TEACHING] fixture_failed err=%s", exc)
            plan = None
    else:
        plan = await plan_visual_teaching_with_retry(
            authored=pkg,
            vtse_template=vtse_template,
            language=language,
            concept_name=concept_name,
            continuity=continuity,
        )

    if plan is None:
        session.visual_teaching_status = STATUS_FAILED
        session.visual_teaching_plan = None
        return None

    session.visual_teaching_plan = plan.model_dump()
    session.visual_teaching_scene_index = 0
    session.visual_teaching_beat_index = 0
    session.visual_teaching_sentence_index = -1
    session.visual_teaching_skipped_scenes = []
    session.visual_teaching_status = STATUS_PLAYING
    return plan


def current_cursor(session: Session) -> tuple[int, int, int]:
    raw_si = getattr(session, "visual_teaching_sentence_index", -1)
    sentence_i = -1 if raw_si is None else int(raw_si)
    return (
        int(getattr(session, "visual_teaching_scene_index", 0) or 0),
        int(getattr(session, "visual_teaching_beat_index", 0) or 0),
        sentence_i,
    )


def plan_exhausted(session: Session, plan: VisualTeachingPlan) -> bool:
    si, bi, _ = current_cursor(session)
    if si >= len(plan.scenes):
        return True
    if si == len(plan.scenes) - 1 and bi >= len(plan.scenes[si].beats):
        return True
    return False


def advance_beat(session: Session, plan: VisualTeachingPlan) -> bool:
    """Advance past current beat. Returns True if another beat/scene remains."""
    si = int(getattr(session, "visual_teaching_scene_index", 0) or 0)
    bi = int(getattr(session, "visual_teaching_beat_index", 0) or 0)
    if si >= len(plan.scenes):
        return False
    scene = plan.scenes[si]
    if bi + 1 < len(scene.beats):
        session.visual_teaching_beat_index = bi + 1
        session.visual_teaching_sentence_index = -1
        return True
    if si + 1 < len(plan.scenes):
        session.visual_teaching_scene_index = si + 1
        session.visual_teaching_beat_index = 0
        session.visual_teaching_sentence_index = -1
        return True
    session.visual_teaching_beat_index = bi + 1
    return False


def record_sentence_progress(
    session: Session,
    sentence_index: int,
    *,
    scene_index: Optional[int] = None,
    beat_index: Optional[int] = None,
) -> bool:
    """
    In-memory sentence cursor update (unit tests / non-persisted fixtures).

    Production path must use ``atomic_record_sentence_progress`` so concurrent
    next/done cannot be overwritten by a stale full-document Session.save().
    """
    if is_stage_done(session):
        return False
    status = str(getattr(session, "visual_teaching_status", "") or "")
    if status != STATUS_PLAYING:
        return False
    if scene_index is None or beat_index is None:
        return False
    try:
        want_s = int(scene_index)
        want_b = int(beat_index)
        si = int(sentence_index)
    except (TypeError, ValueError):
        return False
    if si < 0 or want_s < 0 or want_b < 0:
        return False
    cur_s = int(getattr(session, "visual_teaching_scene_index", 0) or 0)
    cur_b = int(getattr(session, "visual_teaching_beat_index", 0) or 0)
    if want_s != cur_s or want_b != cur_b:
        return False
    current_raw = getattr(session, "visual_teaching_sentence_index", -1)
    current = -1 if current_raw is None else int(current_raw)
    if si <= current:
        return False
    session.visual_teaching_sentence_index = si
    return True


def _session_oid(session_id: Any) -> Optional[PydanticObjectId]:
    if session_id is None:
        return None
    if isinstance(session_id, PydanticObjectId):
        return session_id
    try:
        return PydanticObjectId(str(session_id))
    except Exception:  # noqa: BLE001
        return None


async def atomic_record_sentence_progress(
    session_id: Any,
    *,
    scene_index: int,
    beat_index: int,
    sentence_index: int,
) -> bool:
    """
    Conditionally ``$set`` only ``visual_teaching_sentence_index``.

    Never writes scene/beat/status/flow/plan. Safe across workers: a stale
    checkpoint whose scene/beat no longer match is a no-op write.
    """
    oid = _session_oid(session_id)
    if oid is None:
        return False
    try:
        want_s = int(scene_index)
        want_b = int(beat_index)
        si = int(sentence_index)
    except (TypeError, ValueError):
        return False
    if si < 0 or want_s < 0 or want_b < 0:
        return False

    coll = Session.get_pymongo_collection()
    result = await coll.update_one(
        {
            "_id": oid,
            "visual_teaching_status": STATUS_PLAYING,
            "visual_teaching_scene_index": want_s,
            "visual_teaching_beat_index": want_b,
            "visual_teaching_sentence_index": {"$lt": si},
        },
        {
            "$set": {
                "visual_teaching_sentence_index": si,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    accepted = bool(getattr(result, "modified_count", 0))
    if accepted:
        logger.debug(
            "[VISUAL_TEACHING] sentence_atomic_accepted "
            "scene=%s beat=%s sentence=%s",
            want_s,
            want_b,
            si,
        )
    else:
        logger.debug(
            "[VISUAL_TEACHING] sentence_atomic_stale "
            "scene=%s beat=%s sentence=%s",
            want_s,
            want_b,
            si,
        )
    return accepted


def compute_next_cursor(
    plan: VisualTeachingPlan, scene_index: int, beat_index: int
) -> Optional[Tuple[int, int]]:
    """Return (scene, beat) after leaving the given beat, or None if exhausted."""
    si = int(scene_index)
    bi = int(beat_index)
    if si < 0 or si >= len(plan.scenes):
        return None
    scene = plan.scenes[si]
    if bi + 1 < len(scene.beats):
        return (si, bi + 1)
    if si + 1 < len(plan.scenes):
        return (si + 1, 0)
    return None


def hydrate_vt_fields(session: Session, doc: Mapping[str, Any]) -> None:
    """Copy Visual Teaching cursor/status fields from a Mongo document onto session."""
    if "visual_teaching_scene_index" in doc:
        session.visual_teaching_scene_index = int(
            doc.get("visual_teaching_scene_index") or 0
        )
    if "visual_teaching_beat_index" in doc:
        session.visual_teaching_beat_index = int(
            doc.get("visual_teaching_beat_index") or 0
        )
    if "visual_teaching_sentence_index" in doc:
        raw = doc.get("visual_teaching_sentence_index")
        session.visual_teaching_sentence_index = (
            -1 if raw is None else int(raw)
        )
    if "visual_teaching_status" in doc:
        session.visual_teaching_status = str(
            doc.get("visual_teaching_status") or STATUS_IDLE
        )
    if "visual_teaching_skipped_scenes" in doc:
        session.visual_teaching_skipped_scenes = list(
            doc.get("visual_teaching_skipped_scenes") or []
        )
    if "flow_state" in doc:
        session.flow_state = str(doc.get("flow_state") or "idle")
    if "concept_teaching_stage_index" in doc:
        session.concept_teaching_stage_index = int(
            doc.get("concept_teaching_stage_index") or 0
        )


async def atomic_try_advance_from_beat(
    session_id: Any,
    *,
    expected_scene: int,
    expected_beat: int,
    next_scene: int,
    next_beat: int,
    skipped_scenes: Optional[List[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Conditionally advance cursor from expected beat → next beat.

    Returns the AFTER document when this caller won; None if the expected beat
    was already consumed (or status/flow no longer matches).
    """
    oid = _session_oid(session_id)
    if oid is None:
        return None
    coll = Session.get_pymongo_collection()
    update: Dict[str, Any] = {
        "$set": {
            "visual_teaching_scene_index": int(next_scene),
            "visual_teaching_beat_index": int(next_beat),
            "visual_teaching_sentence_index": -1,
            "updated_at": datetime.utcnow(),
        }
    }
    if skipped_scenes:
        update["$addToSet"] = {
            "visual_teaching_skipped_scenes": {
                "$each": [int(x) for x in skipped_scenes]
            }
        }
    after = await coll.find_one_and_update(
        {
            "_id": oid,
            "visual_teaching_status": STATUS_PLAYING,
            "flow_state": FLOW_VISUAL_TEACHING,
            "visual_teaching_scene_index": int(expected_scene),
            "visual_teaching_beat_index": int(expected_beat),
        },
        update,
        return_document=ReturnDocument.AFTER,
    )
    return after


async def atomic_claim_leave_visual_teaching(
    session_id: Any,
    *,
    expected_scene: Optional[int] = None,
    expected_beat: Optional[int] = None,
    new_stage_index: Optional[int] = None,
    claim_vtse_opening: bool = False,
    concept_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Atomically leave Visual Teaching flow (status → done).

    Default: flow VT → idle.
    When ``claim_vtse_opening`` is True (next stage is VTSE): flow VT →
    ``concept_vtse_opening`` and durable opening status → starting in the *same*
    write so generic idle auto-explain never sees an unclaimed window.

    Only one concurrent completion wins. Returns the BEFORE document when this
    caller claimed the transition; None if flow already left VT.
    """
    oid = _session_oid(session_id)
    if oid is None:
        return None
    filt: Dict[str, Any] = {
        "_id": oid,
        "flow_state": FLOW_VISUAL_TEACHING,
    }
    # When identity provided, prefer claiming from that playing beat; also allow
    # reconcile when status is already done but flow still VT.
    if expected_scene is not None and expected_beat is not None:
        filt["$or"] = [
            {
                "visual_teaching_status": STATUS_PLAYING,
                "visual_teaching_scene_index": int(expected_scene),
                "visual_teaching_beat_index": int(expected_beat),
            },
            {"visual_teaching_status": STATUS_DONE},
        ]
    if claim_vtse_opening:
        from app.services.pedagogy.vtse_opening_claim import (
            FLOW_VTSE_OPENING,
            VTSE_OPENING_STARTING,
        )

        idx = int(concept_index) if concept_index is not None else 0
        set_fields: Dict[str, Any] = {
            "flow_state": FLOW_VTSE_OPENING,
            "visual_teaching_status": STATUS_DONE,
            "concept_vtse_opening_status": VTSE_OPENING_STARTING,
            "concept_vtse_opening_for_index": idx,
            "updated_at": datetime.utcnow(),
        }
    else:
        set_fields = {
            "flow_state": "idle",
            "visual_teaching_status": STATUS_DONE,
            "updated_at": datetime.utcnow(),
        }
    if new_stage_index is not None:
        set_fields["concept_teaching_stage_index"] = int(new_stage_index)
    coll = Session.get_pymongo_collection()
    before = await coll.find_one_and_update(
        filt,
        {"$set": set_fields},
        return_document=ReturnDocument.BEFORE,
    )
    return before


def cursor_is_past(
    *,
    cur_scene: int,
    cur_beat: int,
    expected_scene: int,
    expected_beat: int,
) -> bool:
    if cur_scene > expected_scene:
        return True
    if cur_scene == expected_scene and cur_beat > expected_beat:
        return True
    return False


def advance_ack(
    *,
    outcome: AdvanceOutcome,
    scene_index: int,
    beat_index: int,
    status: str,
    flow_state: str,
    sentence_index: int = -1,
) -> Dict[str, Any]:
    return {
        "type": "visual_teaching_advance_ack",
        "outcome": outcome,
        "scene_index": int(scene_index),
        "beat_index": int(beat_index),
        "sentence_index": int(sentence_index),
        "status": status,
        "flow_state": flow_state,
    }


def mark_done(session: Session) -> None:
    session.visual_teaching_status = STATUS_DONE


def image_path(concept_id: str, asset_key: str) -> str:
    return f"/curriculum/concepts/{concept_id}/visual-teaching/images/{asset_key}"


def _skipped_set(session: Session) -> Set[int]:
    raw = getattr(session, "visual_teaching_skipped_scenes", None) or []
    out: Set[int] = set()
    for item in raw:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _mark_scene_skipped(session: Session, scene_index: int) -> None:
    skipped = _skipped_set(session)
    skipped.add(int(scene_index))
    session.visual_teaching_skipped_scenes = sorted(skipped)


async def _asset_binary_exists(
    authored_snapshot: Any, asset_key: str
) -> bool:
    pkg = normalize_visual_teaching(authored_snapshot)
    if pkg is None:
        return False
    for img in pkg.images:
        if img.asset_key == asset_key:
            if not img.storage_key:
                return False
            try:
                return await get_visual_teaching_storage().exists(img.storage_key)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "[VISUAL_TEACHING] exists_check_failed asset_key=%s", asset_key
                )
                return False
    return False


async def skip_to_next_playable_scene(
    session: Session,
    plan: VisualTeachingPlan,
    *,
    authored_snapshot: Any,
    concept_id: str = "",
) -> bool:
    """
    If current scene binary is missing, skip forward to the next playable scene.
    Returns True when a playable scene/beat is positioned; False if none remain.
    """
    while True:
        si, bi, _ = current_cursor(session)
        if si >= len(plan.scenes):
            return False
        if bi >= len(plan.scenes[si].beats):
            if not advance_beat(session, plan):
                return False
            continue
        scene = plan.scenes[si]
        ok = await _asset_binary_exists(authored_snapshot, scene.asset_key)
        if ok:
            return True
        logger.warning(
            "[VISUAL_TEACHING] missing_binary skip_scene concept_id=%s "
            "scene_index=%s asset_key=%s",
            concept_id,
            si,
            scene.asset_key,
        )
        _mark_scene_skipped(session, si)
        # Jump to next scene, beat 0
        if si + 1 < len(plan.scenes):
            session.visual_teaching_scene_index = si + 1
            session.visual_teaching_beat_index = 0
            session.visual_teaching_sentence_index = -1
            continue
        session.visual_teaching_scene_index = len(plan.scenes)
        session.visual_teaching_beat_index = 0
        return False


def build_beat_payload(
    session: Session,
    plan: VisualTeachingPlan,
    *,
    concept_id: str,
    authored_snapshot: Any,
) -> Dict[str, Any]:
    si, bi, sentence_i = current_cursor(session)
    if si >= len(plan.scenes):
        return {"type": "concept_visual_teaching", "done": True}
    scene = plan.scenes[si]
    if bi >= len(scene.beats):
        return {"type": "concept_visual_teaching", "done": True}
    beat = scene.beats[bi]
    state = visual_state_at(beat, sentence_index=sentence_i)

    pkg = normalize_visual_teaching(authored_snapshot)
    image_meta: Dict[str, Any] = {"asset_key": scene.asset_key}
    regions: List[dict] = []
    anchors: List[dict] = []
    connections: List[dict] = []
    if pkg:
        for img in pkg.images:
            if img.asset_key == scene.asset_key:
                image_meta = {
                    "asset_key": img.asset_key,
                    "mime_type": img.mime_type,
                    "natural_width": img.natural_width,
                    "natural_height": img.natural_height,
                    "title": img.title,
                }
                regions = [r.model_dump() for r in img.regions]
                anchors = [a.model_dump() for a in img.anchors]
                connections = [c.model_dump() for c in img.connections]
                break

    # All writes (FE reveals by speech); plus already_visible for restore ink.
    writes = [
        {"sentence_index": w.sentence_index, "text": w.text} for w in beat.writes
    ]
    visible_writes = [
        w for w in writes if int(w["sentence_index"]) <= sentence_i
    ] if sentence_i >= 0 else []

    sentence_events = [
        {
            "sentence_index": e.sentence_index,
            "patch": e.patch,
        }
        for e in beat.sentence_events
    ]

    return {
        "type": "concept_visual_teaching",
        "done": False,
        "concept_id": concept_id,
        "scene_index": si,
        "beat_index": bi,
        "sentence_index": sentence_i,
        "scene_count": len(plan.scenes),
        "beat_count": len(scene.beats),
        "asset_key": scene.asset_key,
        "image_path": image_path(concept_id, scene.asset_key),
        "image": image_meta,
        "regions": regions,
        "anchors": anchors,
        "connections": connections,
        "visual_state": state.model_dump(),
        "enter_effects": [e.model_dump() for e in beat.enter_effects],
        "speak": beat.speak,
        "writes": writes,
        "visible_writes": visible_writes,
        "sentence_events": sentence_events,
        "capabilities_used": list(plan.capabilities_used or []),
        "skipped_scenes": sorted(_skipped_set(session)),
    }


def step_response(
    session: Session,
    plan: VisualTeachingPlan,
    *,
    concept_id: str,
    authored_snapshot: Any,
    message: str = "",
) -> Dict[str, Any]:
    card = build_beat_payload(
        session,
        plan,
        concept_id=concept_id,
        authored_snapshot=authored_snapshot,
    )
    speak = str(card.get("speak") or message or "")
    return {
        "type": "concept_visual_teaching",
        "message": speak,
        "flow_state": FLOW_VISUAL_TEACHING,
        "visual": card,
        "actions": [
            {"id": ACTION_VISUAL_TEACHING_NEXT, "label": "Continue"},
            {"id": ACTION_VISUAL_TEACHING_DONE, "label": "Done"},
        ],
    }


def parse_sentence_action(
    action: Optional[str],
) -> Optional[tuple[int, int, int]]:
    """
    Parse Visual Teaching sentence checkpoint.

    Required form:
      visual_teaching_sentence:{scene_index}:{beat_index}:{sentence_index}

    Legacy `visual_teaching_sentence:{sentence_index}` is rejected (returns None)
    so stale/uncscoped callbacks cannot mutate the current beat cursor.
    """
    if not action:
        return None
    raw = str(action).strip().lower()
    prefix = ACTION_VISUAL_TEACHING_SENTENCE
    if raw == prefix:
        return None
    if not raw.startswith(prefix + ":"):
        return None
    tail = raw[len(prefix) + 1 :].strip()
    parts = [p.strip() for p in tail.split(":") if p.strip() != ""]
    if len(parts) != 3:
        return None
    try:
        scene_i = int(parts[0])
        beat_i = int(parts[1])
        sentence_i = int(parts[2])
    except ValueError:
        return None
    if scene_i < 0 or beat_i < 0 or sentence_i < 0:
        return None
    return (scene_i, beat_i, sentence_i)


def parse_advance_action(
    action: Optional[str],
) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    """
    Parse Visual Teaching next/done.

    Preferred:
      visual_teaching_next:{scene}:{beat}
      visual_teaching_done:{scene}:{beat}

    Legacy bare ``visual_teaching_next`` / ``visual_teaching_done`` returns
    (kind, None, None) — caller should fill expected cursor from Session.
    """
    if not action:
        return None
    raw = str(action).strip().lower()
    for kind, prefix in (
        ("done", ACTION_VISUAL_TEACHING_DONE),
        ("next", ACTION_VISUAL_TEACHING_NEXT),
    ):
        if raw == prefix:
            return (kind, None, None)
        if raw.startswith(prefix + ":"):
            tail = raw[len(prefix) + 1 :].strip()
            parts = [p.strip() for p in tail.split(":") if p.strip() != ""]
            if len(parts) != 2:
                return None
            try:
                scene_i = int(parts[0])
                beat_i = int(parts[1])
            except ValueError:
                return None
            if scene_i < 0 or beat_i < 0:
                return None
            return (kind, scene_i, beat_i)
    return None


def is_visual_teaching_advance_action(action: Optional[str]) -> bool:
    if not action:
        return False
    if parse_advance_action(action) is not None:
        return True
    raw = str(action).strip().lower()
    return raw in ("quiz", "understand", "start")
