"""Concurrency tests for Visual Teaching atomic Session updates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.visual_teaching import runtime as vt_runtime

_SESS_ID = PydanticObjectId()


class _FakeUpdateResult:
    def __init__(self, modified_count: int):
        self.modified_count = modified_count


class _FakeCollection:
    """In-memory Mongo stand-in that applies conditional $set like Motor."""

    def __init__(self, doc: Dict[str, Any]):
        self.doc = doc
        self.ops: List[Dict[str, Any]] = []

    async def update_one(self, filt: Dict[str, Any], update: Dict[str, Any]):
        self.ops.append({"op": "update_one", "filt": filt, "update": update})
        if not self._matches(filt):
            return _FakeUpdateResult(0)
        self._apply(update)
        return _FakeUpdateResult(1)

    async def find_one_and_update(
        self,
        filt: Dict[str, Any],
        update: Dict[str, Any],
        return_document=None,
    ):
        self.ops.append(
            {"op": "find_one_and_update", "filt": filt, "update": update}
        )
        before = dict(self.doc)
        if not self._matches(filt):
            return None
        self._apply(update)
        # pymongo ReturnDocument.BEFORE == False, AFTER == True
        if return_document is False or str(return_document).endswith("BEFORE"):
            return before
        return dict(self.doc)

    def _match_field(self, key: str, expected: Any) -> bool:
        if key == "_id":
            return self.doc.get("_id") == expected
        if isinstance(expected, dict):
            if "$lt" in expected:
                cur = self.doc.get(key)
                if cur is None:
                    cur = -1
                return int(cur) < int(expected["$lt"])
            if "$ne" in expected:
                return self.doc.get(key) != expected["$ne"]
            if "$in" in expected:
                return self.doc.get(key) in list(expected["$in"])
            if "$exists" in expected:
                exists = key in self.doc
                return exists if expected["$exists"] else not exists
        return self.doc.get(key) == expected

    def _matches(self, filt: Dict[str, Any]) -> bool:
        if filt.get("_id") != self.doc.get("_id"):
            return False
        or_clauses = filt.get("$or")
        and_ok = all(
            k == "_id" or k == "$or" or self._match_field(k, v)
            for k, v in filt.items()
        )
        if or_clauses:
            return and_ok and any(self._match_clause(c) for c in or_clauses)
        return and_ok

    def _match_clause(self, clause: Dict[str, Any]) -> bool:
        return all(self._match_field(k, v) for k, v in clause.items())

    def _apply(self, update: Dict[str, Any]) -> None:
        for k, v in (update.get("$set") or {}).items():
            self.doc[k] = v
        add = update.get("$addToSet") or {}
        for k, spec in add.items():
            cur = list(self.doc.get(k) or [])
            each = spec.get("$each") if isinstance(spec, dict) else [spec]
            for item in each or []:
                if item not in cur:
                    cur.append(item)
            self.doc[k] = cur


def _base_doc(**kwargs) -> Dict[str, Any]:
    doc = {
        "_id": _SESS_ID,
        "visual_teaching_status": "playing",
        "flow_state": "concept_visual_teaching",
        "visual_teaching_scene_index": 0,
        "visual_teaching_beat_index": 0,
        "visual_teaching_sentence_index": -1,
        "visual_teaching_skipped_scenes": [],
        "concept_teaching_stage_index": 0,
    }
    doc.update(kwargs)
    return doc


@pytest.mark.asyncio
async def test_atomic_sentence_never_rewinds_after_advance():
    """Sentence loaded for beat0 writing after next advanced to beat1 → no write."""
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        # Advance wins first.
        after = await vt_runtime.atomic_try_advance_from_beat(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            next_scene=0,
            next_beat=1,
        )
        assert after is not None
        assert coll.doc["visual_teaching_beat_index"] == 1
        assert coll.doc["visual_teaching_sentence_index"] == -1

        # Stale sentence for beat 0 must not write / must not rewind beat.
        ok = await vt_runtime.atomic_record_sentence_progress(
            _SESS_ID, scene_index=0, beat_index=0, sentence_index=2
        )
    assert ok is False
    assert coll.doc["visual_teaching_beat_index"] == 1
    assert coll.doc["visual_teaching_sentence_index"] == -1
    assert coll.doc["visual_teaching_status"] == "playing"
    assert coll.doc["flow_state"] == "concept_visual_teaching"


@pytest.mark.asyncio
async def test_atomic_sentence_then_advance_preserves_new_cursor():
    """Sentence accepted on beat0, then next — sentence cannot clobber beat."""
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        assert (
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=0
            )
            is True
        )
        assert coll.doc["visual_teaching_sentence_index"] == 0
        after = await vt_runtime.atomic_try_advance_from_beat(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            next_scene=0,
            next_beat=1,
        )
        assert after is not None
        # Late duplicate sentence for old beat
        assert (
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=3
            )
            is False
        )
    assert coll.doc["visual_teaching_beat_index"] == 1
    assert coll.doc["visual_teaching_sentence_index"] == -1


@pytest.mark.asyncio
async def test_atomic_sentence_monotonic_within_beat():
    coll = _FakeCollection(_base_doc(visual_teaching_sentence_index=1))
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        assert (
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=1
            )
            is False
        )
        assert (
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=2
            )
            is True
        )
    assert coll.doc["visual_teaching_sentence_index"] == 2


@pytest.mark.asyncio
async def test_duplicate_advance_is_idempotent():
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        first = await vt_runtime.atomic_try_advance_from_beat(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            next_scene=0,
            next_beat=1,
        )
        second = await vt_runtime.atomic_try_advance_from_beat(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            next_scene=0,
            next_beat=1,
        )
    assert first is not None
    assert second is None
    assert coll.doc["visual_teaching_beat_index"] == 1


@pytest.mark.asyncio
async def test_claim_leave_vt_cannot_revert_to_playing():
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        before = await vt_runtime.atomic_claim_leave_visual_teaching(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            new_stage_index=1,
        )
        assert before is not None
        assert coll.doc["flow_state"] == "idle"
        assert coll.doc["visual_teaching_status"] == "done"
        # Second claim fails — cannot reopen VT via sentence either.
        again = await vt_runtime.atomic_claim_leave_visual_teaching(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            new_stage_index=1,
        )
        assert again is None
        ok = await vt_runtime.atomic_record_sentence_progress(
            _SESS_ID, scene_index=0, beat_index=0, sentence_index=9
        )
        assert ok is False
    assert coll.doc["visual_teaching_status"] == "done"
    assert coll.doc["flow_state"] == "idle"


@pytest.mark.asyncio
async def test_stale_sentence_after_scene_transition():
    coll = _FakeCollection(
        _base_doc(
            visual_teaching_scene_index=1,
            visual_teaching_beat_index=0,
            visual_teaching_sentence_index=-1,
        )
    )
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        ok = await vt_runtime.atomic_record_sentence_progress(
            _SESS_ID, scene_index=0, beat_index=1, sentence_index=4
        )
    assert ok is False
    assert coll.doc["visual_teaching_scene_index"] == 1
    assert coll.doc["visual_teaching_beat_index"] == 0


@pytest.mark.asyncio
async def test_concurrent_sentence_storm_then_next_final_cursor():
    """Simulate interleaved sentence $sets racing with next."""
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        # All sentence writes for current beat
        for si in (0, 1, 2):
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=si
            )
        # Next consumes beat 0
        after = await vt_runtime.atomic_try_advance_from_beat(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            next_scene=0,
            next_beat=1,
        )
        assert after is not None
        # Late sentence writes (as if awaited after next) — must not rewind
        for si in (0, 1, 2, 3):
            await vt_runtime.atomic_record_sentence_progress(
                _SESS_ID, scene_index=0, beat_index=0, sentence_index=si
            )
    assert coll.doc["visual_teaching_scene_index"] == 0
    assert coll.doc["visual_teaching_beat_index"] == 1
    assert coll.doc["visual_teaching_sentence_index"] == -1
    assert coll.doc["visual_teaching_status"] == "playing"


def test_parse_advance_action_with_identity():
    assert vt_runtime.parse_advance_action("visual_teaching_next:1:2") == (
        "next",
        1,
        2,
    )
    assert vt_runtime.parse_advance_action("visual_teaching_done:0:0") == (
        "done",
        0,
        0,
    )
    assert vt_runtime.parse_advance_action("visual_teaching_next") == (
        "next",
        None,
        None,
    )


def test_compute_next_cursor():
    plan = vt_runtime.VisualTeachingPlan.model_validate(
        {
            "scenes": [
                {
                    "asset_key": "a",
                    "beats": [
                        {"id": "b0", "speak": "A.", "visual_state": {}},
                        {"id": "b1", "speak": "B.", "visual_state": {}},
                    ],
                },
                {
                    "asset_key": "b",
                    "beats": [{"id": "b2", "speak": "C.", "visual_state": {}}],
                },
            ]
        }
    )
    assert vt_runtime.compute_next_cursor(plan, 0, 0) == (0, 1)
    assert vt_runtime.compute_next_cursor(plan, 0, 1) == (1, 0)
    assert vt_runtime.compute_next_cursor(plan, 1, 0) is None
