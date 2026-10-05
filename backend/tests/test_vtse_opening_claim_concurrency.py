"""Concurrency tests for VT → VTSE opening ownership (no duplicate openings)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.handlers.explanation_handler import should_run_micro_teaching
from app.services.pedagogy import vtse_opening_claim as claim
from app.services.pedagogy.concept_teaching_orchestrator import ConceptTeachingOrchestrator
from app.services.visual_teaching import runtime as vt_runtime

_SESS_ID = PydanticObjectId()


class _FakeUpdateResult:
    def __init__(self, modified_count: int):
        self.modified_count = modified_count


class _FakeCollection:
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

    def _match_clause(self, clause: Dict[str, Any]) -> bool:
        return all(self._match_field(k, v) for k, v in clause.items())

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

    def _apply(self, update: Dict[str, Any]) -> None:
        for k, v in (update.get("$set") or {}).items():
            self.doc[k] = v


def _base_doc(**kwargs) -> Dict[str, Any]:
    doc = {
        "_id": _SESS_ID,
        "current_concept_index": 0,
        "visual_teaching_status": "playing",
        "flow_state": "concept_visual_teaching",
        "visual_teaching_scene_index": 0,
        "visual_teaching_beat_index": 0,
        "visual_teaching_sentence_index": -1,
        "visual_teaching_skipped_scenes": [],
        "concept_teaching_stage_index": 1,
        "concept_teaching_sequence_snapshot": [
            "story_hook",
            "visual_teaching",
            "vtse",
        ],
        "concept_vtse_opening_status": "unclaimed",
        "concept_vtse_opening_for_index": -1,
    }
    doc.update(kwargs)
    return doc


def _session_from_doc(doc: Dict[str, Any]) -> SimpleNamespace:
    session = SimpleNamespace(
        id=_SESS_ID,
        current_concept_index=doc.get("current_concept_index", 0),
        current_concept="heart",
        current_zone=1,
        explanation_mode=None,
        current_step_in_concept=0,
        flow_state=doc.get("flow_state", "idle"),
        visual_teaching_status=doc.get("visual_teaching_status", "idle"),
        visual_teaching_scene_index=doc.get("visual_teaching_scene_index", 0),
        visual_teaching_beat_index=doc.get("visual_teaching_beat_index", 0),
        visual_teaching_sentence_index=doc.get("visual_teaching_sentence_index", -1),
        concept_teaching_stage_index=doc.get("concept_teaching_stage_index", 0),
        concept_teaching_sequence_snapshot=list(
            doc.get("concept_teaching_sequence_snapshot") or []
        ),
        concept_teaching_story_hook_snapshot={"title": "t", "body": "b"},
        concept_teaching_visual_teaching_snapshot={"images": [{"asset_key": "a"}]},
        concept_teaching_await_vtse_done=False,
        concept_vtse_opening_status=doc.get(
            "concept_vtse_opening_status", "unclaimed"
        ),
        concept_vtse_opening_for_index=doc.get("concept_vtse_opening_for_index", -1),
        concept_questions_active=False,
    )

    async def _save() -> None:
        return None

    session.save = _save
    return session


@pytest.mark.asyncio
async def test_leave_vt_for_vtse_claims_opening_atomically():
    coll = _FakeCollection(_base_doc())
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll):
        before = await vt_runtime.atomic_claim_leave_visual_teaching(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            new_stage_index=2,
            claim_vtse_opening=True,
            concept_index=0,
        )
        assert before is not None
        assert coll.doc["flow_state"] == claim.FLOW_VTSE_OPENING
        assert coll.doc["concept_vtse_opening_status"] == claim.VTSE_OPENING_STARTING
        assert coll.doc["visual_teaching_status"] == "done"
        again = await vt_runtime.atomic_claim_leave_visual_teaching(
            _SESS_ID,
            expected_scene=0,
            expected_beat=0,
            new_stage_index=2,
            claim_vtse_opening=True,
            concept_index=0,
        )
        assert again is None


@pytest.mark.asyncio
async def test_atomic_vtse_opening_claim_one_winner():
    coll = _FakeCollection(
        _base_doc(
            flow_state="idle",
            visual_teaching_status="done",
            concept_teaching_stage_index=2,
        )
    )
    with patch.object(claim.Session, "get_pymongo_collection", return_value=coll):
        first = await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
        second = await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
    assert first is not None
    assert second is None
    assert coll.doc["concept_vtse_opening_status"] == "starting"


@pytest.mark.asyncio
async def test_should_run_micro_false_once_opening_claimed():
    session = _session_from_doc(
        _base_doc(
            flow_state=claim.FLOW_VTSE_OPENING,
            concept_vtse_opening_status="starting",
            concept_vtse_opening_for_index=0,
            visual_teaching_status="done",
        )
    )
    with patch(
        "app.services.handlers.explanation_handler._is_teacher_progression",
        return_value=True,
    ):
        assert should_run_micro_teaching(session) is False
        assert (
            should_run_micro_teaching(session, ignore_opening_claim=True) is True
        )


@pytest.mark.asyncio
async def test_concurrent_vtse_start_only_one_opening():
    """Two concurrent _start_vtse_after_hook — exactly one opening generator call."""
    coll = _FakeCollection(
        _base_doc(
            flow_state="idle",
            visual_teaching_status="done",
            concept_teaching_stage_index=2,
        )
    )
    session_a = _session_from_doc(coll.doc)
    session_b = _session_from_doc(coll.doc)
    opening_calls = {"n": 0}

    async def _fake_opening(*_a, **_k):
        opening_calls["n"] += 1
        return {"message": "open", "instruction_timeline_v3": {"beats": [1]}}

    orch = ConceptTeachingOrchestrator()
    with patch.object(claim.Session, "get_pymongo_collection", return_value=coll), patch(
        "app.services.handlers.explanation_handler.should_run_micro_teaching",
        return_value=True,
    ), patch(
        "app.services.handlers.explanation_handler.teacher_micro_teaching_opening",
        new=_fake_opening,
    ):
        r1 = await orch._start_vtse_after_hook(
            session_a,
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
        )
        r2 = await orch._start_vtse_after_hook(
            session_b,
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
        )
    assert opening_calls["n"] == 1
    assert r1 is not None and r1.get("type") == "explanation"
    assert r2 is not None and r2.get("type") == "vtse_opening_ack"
    assert r2.get("outcome") in ("already_starting", "already_started")


@pytest.mark.asyncio
async def test_stale_visual_teaching_next_during_opening_no_second():
    coll = _FakeCollection(
        _base_doc(
            flow_state=claim.FLOW_VTSE_OPENING,
            visual_teaching_status="done",
            concept_teaching_stage_index=2,
            concept_vtse_opening_status="starting",
            concept_vtse_opening_for_index=0,
        )
    )
    session = _session_from_doc(coll.doc)
    orch = ConceptTeachingOrchestrator()
    with patch.object(claim.Session, "get_pymongo_collection", return_value=coll):
        out = await orch.maybe_emit(
            session,
            action="visual_teaching_next:0:0",
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
        )
    assert out is not None
    assert out["type"] in ("visual_teaching_advance_ack", "vtse_opening_ack")
    assert out.get("outcome") in (
        "already_advanced",
        "already_starting",
        "already_started",
    )


@pytest.mark.asyncio
async def test_duplicate_visual_teaching_done_no_second_opening():
    coll = _FakeCollection(
        _base_doc(
            flow_state=claim.FLOW_VTSE_OPENING,
            visual_teaching_status="done",
            concept_teaching_stage_index=2,
            concept_vtse_opening_status="starting",
            concept_vtse_opening_for_index=0,
        )
    )
    session = _session_from_doc(coll.doc)
    orch = ConceptTeachingOrchestrator()
    out = await orch.maybe_emit(
        session,
        action="visual_teaching_done:0:0",
        handler_ctx=object(),
        session_id=_SESS_ID,
        student_id=_SESS_ID,
        topic=object(),
    )
    assert out["type"] in ("visual_teaching_advance_ack", "vtse_opening_ack")


@pytest.mark.asyncio
async def test_generic_ask_during_opening_no_second():
    coll = _FakeCollection(
        _base_doc(
            flow_state=claim.FLOW_VTSE_OPENING,
            visual_teaching_status="done",
            concept_vtse_opening_status="starting",
            concept_vtse_opening_for_index=0,
        )
    )
    session = _session_from_doc(coll.doc)
    orch = ConceptTeachingOrchestrator()
    out = await orch.maybe_emit(
        session,
        action=None,
        user_input=".",
        handler_ctx=object(),
        session_id=_SESS_ID,
        student_id=_SESS_ID,
        topic=object(),
    )
    assert out["type"] == "vtse_opening_ack"
    assert out["outcome"] == "already_starting"


@pytest.mark.asyncio
async def test_opening_failure_retryable_then_one_success():
    coll = _FakeCollection(
        _base_doc(
            flow_state="idle",
            visual_teaching_status="done",
            concept_teaching_stage_index=2,
        )
    )
    with patch.object(claim.Session, "get_pymongo_collection", return_value=coll):
        assert (
            await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
        ) is not None
        assert await claim.atomic_mark_vtse_opening_failed(
            _SESS_ID, concept_index=0
        )
        assert coll.doc["concept_vtse_opening_status"] == "failed"
        assert coll.doc["flow_state"] == "idle"
        # Retry claim succeeds once.
        assert (
            await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
        ) is not None
        assert (
            await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
        ) is None
        assert await claim.atomic_mark_vtse_opening_ready(
            _SESS_ID, concept_index=0
        )
        assert coll.doc["concept_vtse_opening_status"] == "ready"
        # Ready is not retryable without concept change.
        assert (
            await claim.atomic_claim_vtse_opening(_SESS_ID, concept_index=0)
        ) is None


@pytest.mark.asyncio
async def test_tts_off_burst_done_next_quiz_one_opening():
    """Burst: done (claims leave+opening) + next + quiz → one generator."""
    coll = _FakeCollection(_base_doc(concept_teaching_stage_index=1))
    opening_calls = {"n": 0}

    async def _fake_opening(*_a, **_k):
        opening_calls["n"] += 1
        return {
            "message": "vtse",
            "instruction_timeline_v3": {"beats": [{"id": "b1"}]},
        }

    orch = ConceptTeachingOrchestrator()

    async def _run_done(session):
        return await orch._complete_visual_teaching(
            session,
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
            expected_scene=0,
            expected_beat=0,
        )

    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll), patch.object(
        claim.Session, "get_pymongo_collection", return_value=coll
    ), patch(
        "app.services.handlers.explanation_handler.should_run_micro_teaching",
        return_value=True,
    ), patch(
        "app.services.handlers.explanation_handler.teacher_micro_teaching_opening",
        new=_fake_opening,
    ), patch.object(
        orch,
        "_peek_executable_from",
        return_value="vtse",
    ), patch.object(
        orch,
        "_skip_non_executable_stages",
        return_value="vtse",
    ):
        session_done = _session_from_doc(coll.doc)
        # Stage points at visual_teaching so completion advances to vtse.
        session_done.concept_teaching_stage_index = 1
        session_done.concept_teaching_sequence_snapshot = [
            "story_hook",
            "visual_teaching",
            "vtse",
        ]
        r_done = await _run_done(session_done)

        # Stale next while opening starting
        session_next = _session_from_doc(coll.doc)
        r_next = await orch.maybe_emit(
            session_next,
            action="visual_teaching_next:0:0",
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
        )

        # Generic quiz/ask while opening starting / ready
        session_quiz = _session_from_doc(coll.doc)
        r_quiz = await orch.maybe_emit(
            session_quiz,
            action="quiz",
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
        )

    assert opening_calls["n"] == 1
    assert r_done is not None and r_done.get("type") == "explanation"
    assert r_next["type"] in ("visual_teaching_advance_ack", "vtse_opening_ack")
    assert r_quiz["type"] == "vtse_opening_ack"


@pytest.mark.asyncio
async def test_complete_visual_teaching_arms_questions_path_when_vtse_last_ready():
    """After single opening with vtse last, status ready and questions can arm."""
    coll = _FakeCollection(_base_doc(concept_teaching_stage_index=1))

    async def _fake_opening(ctx, session, *_a, **_k):
        session.flow_state = "explaining"
        session.concept_questions_active = True
        return {
            "message": "explore",
            "instruction_timeline_v3": {"beats": []},
        }

    orch = ConceptTeachingOrchestrator()
    with patch.object(vt_runtime.Session, "get_pymongo_collection", return_value=coll), patch.object(
        claim.Session, "get_pymongo_collection", return_value=coll
    ), patch(
        "app.services.handlers.explanation_handler.should_run_micro_teaching",
        return_value=True,
    ), patch(
        "app.services.handlers.explanation_handler.teacher_micro_teaching_opening",
        new=_fake_opening,
    ), patch.object(orch, "_peek_executable_from", return_value="vtse"), patch.object(
        orch, "_skip_non_executable_stages", return_value="vtse"
    ):
        session = _session_from_doc(coll.doc)
        session.concept_teaching_stage_index = 1
        out = await orch._complete_visual_teaching(
            session,
            handler_ctx=object(),
            session_id=_SESS_ID,
            student_id=_SESS_ID,
            topic=object(),
            expected_scene=0,
            expected_beat=0,
        )
    assert out["type"] == "explanation"
    assert coll.doc["concept_vtse_opening_status"] == "ready"
    assert coll.doc["visual_teaching_status"] == "done"
