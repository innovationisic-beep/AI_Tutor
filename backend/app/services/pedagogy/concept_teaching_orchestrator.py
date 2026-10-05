"""Concept teaching orchestrator — Story Hook / Visual Teaching around VTSE."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.learning.sessions import Session
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.concept_teaching_sequence import (
    normalize_story_hook,
    resolve_effective_teaching_sequence,
    story_hook_has_content,
)
from app.services.language.tutor_language_policy import resolve_mode_for_session
from app.services.story_hook import runtime as story_hook_runtime
from app.services.story_hook.plan_schema import plan_from_stored
from app.services.visual_teaching import runtime as visual_teaching_runtime
from app.services.visual_teaching.authored import (
    normalize_visual_teaching,
    visual_teaching_has_content,
)
from app.services.pedagogy import vtse_opening_claim
from app.services.pedagogy.vtse_stage_completion import (
    can_complete_vtse_stage,
    is_vtse_stage_done_action,
    parse_vtse_stage_done_identity,
    reject_vtse_stage_done,
    vtse_timeline_requires_playback,
)

logger = logging.getLogger(__name__)


def _session_collection():
    """Mongo collection when Beanie is initialized; None for in-memory stubs."""
    try:
        return Session.get_pymongo_collection()
    except Exception:
        return None

FLOW_STORY_HOOK = "concept_story_hook"
FLOW_VISUAL_TEACHING = visual_teaching_runtime.FLOW_VISUAL_TEACHING
FLOW_VTSE_OPENING = vtse_opening_claim.FLOW_VTSE_OPENING
ACTION_STORY_HOOK_DONE = "story_hook_done"
ACTION_VTSE_STAGE_DONE = "concept_vtse_stage_done"
ACTION_VISUAL_TEACHING_DONE = visual_teaching_runtime.ACTION_VISUAL_TEACHING_DONE
ACTION_VISUAL_TEACHING_NEXT = visual_teaching_runtime.ACTION_VISUAL_TEACHING_NEXT

# The frontend reports "narration finished" with the same action it always has;
# the backend decides whether that means the next step or the end of the stage.
_STORY_HOOK_ADVANCE_ACTIONS = frozenset(
    {ACTION_STORY_HOOK_DONE, "story_hook_next", "quiz", "understand", "start"}
)
_VISUAL_TEACHING_LEGACY_ADVANCE = frozenset(
    {
        ACTION_VISUAL_TEACHING_DONE,
        ACTION_VISUAL_TEACHING_NEXT,
        "quiz",
        "understand",
        "start",
    }
)


def zone0_blocks_concept_teaching(session: Any) -> bool:
    """True while Zone 0 is active and not yet finished (ready / phase done)."""
    if int(getattr(session, "current_zone", 0) or 0) != 0:
        return False
    phase = str(getattr(session, "zone0_phase", "") or "").strip().lower()
    return phase != "done"


class ConceptTeachingOrchestrator:
    """
    Ordered concept stages around the existing VTSE engine.

    Does not modify VTSE timeline internals. Media stages are skipped until
    a media implementation exists (media_available=False).
    """

    def __init__(
        self,
        *,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def ensure_sequence_snapshot(self, session: Session) -> List[str]:
        """Freeze effective sequence + story hook + visual teaching for current concept."""
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        _raw_for = getattr(session, "concept_teaching_for_index", -1)
        for_idx = -1 if _raw_for is None else int(_raw_for)
        existing = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        if for_idx == idx and existing:
            return existing

        concept = await self._resolve_current_concept(session)
        hook = normalize_story_hook(
            getattr(concept, "story_hook", None) if concept is not None else None
        )
        vt_pkg = normalize_visual_teaching(
            getattr(concept, "visual_teaching", None) if concept is not None else None
        )
        from app.services.curriculum.concept_teaching_sequence import (
            select_frozen_teaching_sequence,
        )

        seq, source = select_frozen_teaching_sequence(concept)
        session.concept_teaching_for_index = idx
        session.concept_teaching_sequence_snapshot = list(seq)
        session.concept_teaching_sequence_source = source
        session.concept_teaching_stage_index = 0
        session.concept_teaching_story_hook_snapshot = (
            hook.model_dump() if hook is not None else None
        )
        session.concept_teaching_visual_teaching_snapshot = (
            vt_pkg.model_dump() if vt_pkg is not None else None
        )
        from app.services.vtse_visuals.authored import normalize_vtse_visuals

        session.concept_teaching_vtse_visuals_snapshot = normalize_vtse_visuals(
            getattr(concept, "vtse_visuals", None) if concept is not None else None
        )
        session.concept_teaching_await_vtse_done = False
        # New concept → previous plans / VTSE opening claim must not leak in.
        story_hook_runtime.reset_runtime(session)
        visual_teaching_runtime.reset_runtime(session)
        vtse_opening_claim.reset_vtse_opening(session)
        await session.save()
        logger.info(
            "[CONCEPT_TEACH] snapshot concept_index=%s sequence=%s has_hook=%s has_vt=%s",
            idx,
            seq,
            hook is not None,
            vt_pkg is not None,
        )
        return list(seq)

    def current_stage(self, session: Session) -> Optional[str]:
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
        if idx < 0 or idx >= len(seq):
            return None
        return str(seq[idx])

    def _has_post_vtse_stage(self, session: Session, from_idx: int) -> bool:
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        later = seq[from_idx + 1 :]
        return "story_hook" in later or "visual_teaching" in later

    def should_defer_concept_questions(self, session: Session) -> bool:
        """True while a VTSE timeline must finish before Concept Check."""
        if bool(getattr(session, "concept_teaching_await_vtse_done", False)):
            return True
        if self.current_stage(session) == "vtse" and vtse_timeline_requires_playback(
            session
        ):
            return True
        return False

    def mark_vtse_opening_started(self, session: Session) -> bool:
        """
        Called from teacher_micro_teaching_opening.

        Returns True when a real VTSE timeline must play before Concept Check.
        Does not move the teaching stage past VTSE. A missing later stage is
        not permission to arm questions.
        """
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
        if not seq:
            return False
        if idx < len(seq) and seq[idx] != "vtse":
            try:
                idx = seq.index("vtse")
                session.concept_teaching_stage_index = idx
            except ValueError:
                return False
        if idx >= len(seq) or seq[idx] != "vtse":
            return False
        if not vtse_timeline_requires_playback(session):
            return False
        session.concept_teaching_await_vtse_done = True
        return True

    def _advance_stage(self, session: Session) -> None:
        session.concept_teaching_stage_index = (
            int(getattr(session, "concept_teaching_stage_index", 0) or 0) + 1
        )

    def _skip_non_executable_stages(self, session: Session) -> Optional[str]:
        """
        Advance past empty story_hook / visual_teaching / media without recursion.
        Returns the next executable stage name, or None (vtse / exhausted).
        """
        for _ in range(8):
            stage = self.current_stage(session)
            if stage is None or stage == "vtse":
                return stage
            if stage == "media":
                self._advance_stage(session)
                continue
            if stage == "story_hook":
                snap = getattr(session, "concept_teaching_story_hook_snapshot", None)
                if not story_hook_has_content(snap):
                    self._advance_stage(session)
                    continue
                return "story_hook"
            if stage == "visual_teaching":
                snap = getattr(
                    session, "concept_teaching_visual_teaching_snapshot", None
                )
                if not visual_teaching_has_content(snap):
                    self._advance_stage(session)
                    continue
                return "visual_teaching"
            self._advance_stage(session)
        return self.current_stage(session)

    def _peek_executable_from(
        self, session: Session, start_index: Optional[int]
    ) -> Optional[str]:
        """Read-only peek at next executable stage starting at ``start_index``."""
        if start_index is None:
            return None
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        i = int(start_index)
        for _ in range(8):
            if i < 0 or i >= len(seq):
                return None
            stage = str(seq[i])
            if stage == "vtse":
                return "vtse"
            if stage == "media":
                i += 1
                continue
            if stage == "story_hook":
                snap = getattr(session, "concept_teaching_story_hook_snapshot", None)
                if not story_hook_has_content(snap):
                    i += 1
                    continue
                return "story_hook"
            if stage == "visual_teaching":
                snap = getattr(
                    session, "concept_teaching_visual_teaching_snapshot", None
                )
                if not visual_teaching_has_content(snap):
                    i += 1
                    continue
                return "visual_teaching"
            i += 1
        return None

    @staticmethod
    def _vt_done_advance_ack(session: Session) -> Dict[str, Any]:
        return visual_teaching_runtime.advance_ack(
            outcome="already_advanced",
            scene_index=int(getattr(session, "visual_teaching_scene_index", 0) or 0),
            beat_index=int(getattr(session, "visual_teaching_beat_index", 0) or 0),
            status=visual_teaching_runtime.STATUS_DONE,
            flow_state=str(getattr(session, "flow_state", "idle") or "idle"),
            sentence_index=int(
                getattr(session, "visual_teaching_sentence_index", -1) or -1
            ),
        )

    async def maybe_emit(
        self,
        session: Session,
        *,
        action: Optional[str],
        handler_ctx: Any = None,
        session_id: Optional[PydanticObjectId] = None,
        student_id: Optional[PydanticObjectId] = None,
        topic: Any = None,
        user_input: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        # FlowCheckpoint pause/continue must reach session_service handlers.
        # Returning noop here swallows them (FE: "Could not clear the checkpoint").
        _fc = str(action or "").strip().lower()
        if _fc.startswith("flow_checkpoint_continue") or _fc.startswith(
            "flow_checkpoint_pause"
        ):
            return None

        if zone0_blocks_concept_teaching(session):
            flow = str(getattr(session, "flow_state", "idle") or "idle")
            if flow in (FLOW_STORY_HOOK, FLOW_VISUAL_TEACHING, FLOW_VTSE_OPENING) or bool(
                getattr(session, "concept_teaching_await_vtse_done", False)
            ):
                session.flow_state = "idle"
                session.concept_teaching_await_vtse_done = False
            return None

        flow = str(getattr(session, "flow_state", "idle") or "idle")

        # VTSE opening in flight — never fall through to idle auto-explain.
        if flow == FLOW_VTSE_OPENING or vtse_opening_claim.is_opening_in_progress(
            session
        ):
            advance_while_opening = visual_teaching_runtime.parse_advance_action(action)
            if (
                advance_while_opening is not None
                and visual_teaching_runtime.is_stage_done(session)
            ):
                return self._vt_done_advance_ack(session)
            return vtse_opening_claim.acknowledge_existing_opening(session)

        if flow == FLOW_VISUAL_TEACHING:
            sentence_parsed = visual_teaching_runtime.parse_sentence_action(action)
            if sentence_parsed is not None:
                scene_i, beat_i, sentence_i = sentence_parsed
                sid = getattr(session, "id", None) or session_id
                if sid is not None:
                    changed = (
                        await visual_teaching_runtime.atomic_record_sentence_progress(
                            sid,
                            scene_index=scene_i,
                            beat_index=beat_i,
                            sentence_index=sentence_i,
                        )
                    )
                else:
                    # Unit-test fixtures without a persisted Session id.
                    changed = visual_teaching_runtime.record_sentence_progress(
                        session,
                        sentence_i,
                        scene_index=scene_i,
                        beat_index=beat_i,
                    )
                # State-sync only — never full-document save; never derive flow.
                return {
                    "type": "visual_teaching_sentence_ack",
                    "scene_index": scene_i,
                    "beat_index": beat_i,
                    "sentence_index": sentence_i,
                    "accepted": bool(changed),
                }
            advance_parsed = visual_teaching_runtime.parse_advance_action(action)
            is_legacy_advance = (
                action is not None
                and str(action).strip().lower() in _VISUAL_TEACHING_LEGACY_ADVANCE
            )
            if advance_parsed is not None or is_legacy_advance:
                if visual_teaching_runtime.is_stage_done(session):
                    return await self._complete_visual_teaching(
                        session,
                        handler_ctx=handler_ctx,
                        session_id=session_id,
                        student_id=student_id,
                        topic=topic,
                        expected_scene=(
                            advance_parsed[1] if advance_parsed else None
                        ),
                        expected_beat=(
                            advance_parsed[2] if advance_parsed else None
                        ),
                    )
                return await self._advance_visual_teaching(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                    action=action,
                )
            return {"type": "noop"}

        if flow == FLOW_STORY_HOOK:
            if story_hook_runtime.is_awaiting_student(session):
                reply = (user_input or "").strip()
                if reply and not reply.startswith("__action:"):
                    return await self._answer_story_hook_question(session, reply)
                return {"type": "noop"}
            if action in _STORY_HOOK_ADVANCE_ACTIONS:
                return await self._advance_story_hook(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                )
            return {"type": "noop"}

        awaiting_vtse = bool(
            getattr(session, "concept_teaching_await_vtse_done", False)
        )
        stage_done = is_vtse_stage_done_action(action)
        if stage_done or (
            awaiting_vtse and action in ("quiz", "understand", "start")
        ):
            identity = (
                parse_vtse_stage_done_identity(user_input) if stage_done else None
            )
            if stage_done:
                from app.services.pedagogy.vtse_stage_completion import (
                    bind_active_vtse_timeline,
                )

                identity = bind_active_vtse_timeline(session, identity)
            return await self._complete_vtse_stage(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
                expected_timeline_identity=identity,
            )

        # FE may send story_hook_done after DB already left concept_story_hook
        if action == ACTION_STORY_HOOK_DONE and flow == "idle":
            await self.ensure_sequence_snapshot(session)
            stage = self._skip_non_executable_stages(session)
            if stage == "story_hook":
                return await self._advance_story_hook(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                )
            if stage == "visual_teaching":
                return await self._advance_visual_teaching(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                    action=action,
                )
            if stage == "vtse":
                return await self._start_vtse_after_hook(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                )

        # Stale VT next/done after completion — never fall through to idle auto-explain.
        advance_parsed_any = visual_teaching_runtime.parse_advance_action(action)
        if (
            advance_parsed_any is not None
            and visual_teaching_runtime.is_stage_done(session)
            and flow != FLOW_VISUAL_TEACHING
        ):
            return self._vt_done_advance_ack(session)

        if (
            advance_parsed_any is not None
            and advance_parsed_any[0] == "done"
            and flow == "idle"
            and not visual_teaching_runtime.is_stage_done(session)
        ):
            await self.ensure_sequence_snapshot(session)
            stage = self._skip_non_executable_stages(session)
            if stage == "visual_teaching":
                return await self._advance_visual_teaching(
                    session,
                    handler_ctx=handler_ctx,
                    session_id=session_id,
                    student_id=student_id,
                    topic=topic,
                    action=action,
                )
            return {"type": "noop"}

        # Opening already claimed/ready — block generic idle fallthrough for VTSE.
        # Do not intercept non-idle flows (concept questions, explaining, etc.).
        if flow == "idle" and vtse_opening_claim.is_opening_claimed_or_ready(session):
            return vtse_opening_claim.acknowledge_existing_opening(session)

        # Only emit pre-VTSE stages when idle (same gate as micro-teaching entry).
        if flow != "idle":
            return None

        await self.ensure_sequence_snapshot(session)
        stage = self._skip_non_executable_stages(session)
        if stage == "story_hook":
            emitted = await self._emit_story_hook_step(session)
            if emitted is not None:
                return emitted
            return await self._complete_story_hook(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )
        if stage == "visual_teaching":
            emitted = await self._emit_visual_teaching_beat(session)
            if emitted is not None:
                return emitted
            return await self._complete_visual_teaching(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )
        # vtse or exhausted → let existing idle → VTSE path run (with atomic claim)
        return None

    async def _complete_vtse_stage(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
        expected_timeline_identity: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ok, reason = can_complete_vtse_stage(session, expected_timeline_identity)
        tid = str((expected_timeline_identity or {}).get("timeline_id") or "")
        if not ok:
            return reject_vtse_stage_done(
                reason,
                session_id=session_id or getattr(session, "id", None),
                concept_index=getattr(session, "current_concept_index", None),
                timeline_id=tid,
            )
        logger.info(
            "[VTSE_STAGE] accepted session_id=%s concept_index=%s timeline_id=%s",
            session_id or getattr(session, "id", None),
            getattr(session, "current_concept_index", None),
            tid,
        )

        await self.ensure_sequence_snapshot(session)
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
        new_idx = idx + 1 if idx < len(seq) and seq[idx] == "vtse" else idx
        session.concept_teaching_stage_index = new_idx
        session.concept_teaching_await_vtse_done = False
        session.flow_state = "idle"
        sid = session_id or getattr(session, "id", None)
        coll = _session_collection() if sid is not None else None
        if coll is not None:
            from datetime import datetime

            claimed = await coll.find_one_and_update(
                {
                    "_id": sid,
                    "concept_teaching_await_vtse_done": True,
                    "concept_teaching_stage_index": idx,
                    "flow_checkpoint_pending": {"$ne": True},
                },
                {
                    "$set": {
                        "concept_teaching_await_vtse_done": False,
                        "concept_teaching_stage_index": new_idx,
                        "flow_state": "idle",
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            if claimed is None:
                return reject_vtse_stage_done(
                    "stage_consumed",
                    session_id=sid,
                    concept_index=getattr(session, "current_concept_index", None),
                    timeline_id=tid,
                )
        else:
            await session.save()

        next_stage = self._skip_non_executable_stages(session)
        if next_stage == "story_hook":
            emitted = await self._emit_story_hook_step(session)
            if emitted is not None:
                return emitted
        if next_stage == "visual_teaching":
            emitted = await self._emit_visual_teaching_beat(session)
            if emitted is not None:
                return emitted
            # Planner failed → skip stage
            return await self._complete_visual_teaching(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )
        return await self._arm_post_concept_questions(
            session,
            handler_ctx=handler_ctx,
            session_id=session_id,
            student_id=student_id,
            topic=topic,
        )

    async def _complete_story_hook(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
    ) -> Optional[Dict[str, Any]]:
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
        if idx < len(seq) and seq[idx] == "story_hook":
            session.concept_teaching_stage_index = idx + 1
        elif "story_hook" in seq:
            try:
                session.concept_teaching_stage_index = seq.index("story_hook") + 1
            except ValueError:
                pass
        session.flow_state = "idle"
        await session.save()

        next_stage = self._skip_non_executable_stages(session)
        if next_stage == "vtse":
            return await self._start_vtse_after_hook(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )
        if next_stage == "story_hook":
            emitted = await self._emit_story_hook_step(session)
            if emitted is not None:
                return emitted
        if next_stage == "visual_teaching":
            emitted = await self._emit_visual_teaching_beat(session)
            if emitted is not None:
                return emitted
            return await self._complete_visual_teaching(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )
        return await self._arm_post_concept_questions(
            session,
            handler_ctx=handler_ctx,
            session_id=session_id,
            student_id=student_id,
            topic=topic,
        )

    async def _start_vtse_after_hook(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
        opening_already_claimed: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if (
            handler_ctx is None
            or session_id is None
            or student_id is None
            or topic is None
        ):
            logger.warning("[CONCEPT_TEACH] vtse_after_hook_missing_ctx")
            return None

        from app.services.handlers.explanation_handler import (
            should_run_micro_teaching,
            teacher_micro_teaching_opening,
        )

        cc = (getattr(session, "current_concept", None) or "").strip()
        c_idx = vtse_opening_claim.concept_index(session)

        if vtse_opening_claim.is_opening_ready(session):
            return vtse_opening_claim.acknowledge_existing_opening(session)

        if not opening_already_claimed:
            if vtse_opening_claim.is_opening_in_progress(session):
                return vtse_opening_claim.acknowledge_existing_opening(session)
            # Gate: only claim when micro-teaching is the intended Zone 1 path.
            if not should_run_micro_teaching(session, ignore_opening_claim=True):
                return None
            claimed = await vtse_opening_claim.atomic_claim_vtse_opening(
                session_id,
                concept_index=c_idx,
                set_flow_opening=True,
            )
            if claimed is None:
                # Refresh in-memory status from concurrent winner if possible.
                return vtse_opening_claim.acknowledge_existing_opening(session)
            vtse_opening_claim.hydrate_opening_fields(
                session,
                {
                    "concept_vtse_opening_status": vtse_opening_claim.VTSE_OPENING_STARTING,
                    "concept_vtse_opening_for_index": c_idx,
                    "flow_state": FLOW_VTSE_OPENING,
                },
            )
        elif not should_run_micro_teaching(session, ignore_opening_claim=True):
            # Claim held from leave-VT but micro path disabled — release retryably.
            await vtse_opening_claim.atomic_mark_vtse_opening_failed(
                session_id, concept_index=c_idx
            )
            return None

        try:
            body = await teacher_micro_teaching_opening(
                handler_ctx, session, session_id, student_id, topic
            )
        except Exception:  # noqa: BLE001
            logger.exception("[CONCEPT_TEACH] vtse_opening_failed concept_index=%s", c_idx)
            await vtse_opening_claim.atomic_mark_vtse_opening_failed(
                session_id, concept_index=c_idx
            )
            session.concept_vtse_opening_status = vtse_opening_claim.VTSE_OPENING_FAILED
            session.flow_state = "idle"
            raise

        await vtse_opening_claim.atomic_mark_vtse_opening_ready(
            session_id, concept_index=c_idx
        )
        session.concept_vtse_opening_status = vtse_opening_claim.VTSE_OPENING_READY

        if isinstance(body, dict):
            # Opening may already be an ack if a nested guard fired.
            if str(body.get("type") or "") == "vtse_opening_ack":
                return body
            return {
                "type": "explanation",
                "current_concept": cc,
                **body,
            }
        return {
            "type": "explanation",
            "message": str(body).strip(),
            "current_concept": cc,
        }

    async def _arm_post_concept_questions(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
    ) -> Dict[str, Any]:
        if (
            handler_ctx is None
            or session_id is None
            or student_id is None
            or topic is None
        ):
            session.flow_state = "idle"
            await session.save()
            return {"type": "noop"}

        if bool(getattr(session, "concept_questions_active", False)):
            return {"type": "noop"}

        from app.services.handlers.concept_question_orchestrator import (
            arm_concept_questions_after_opening,
        )

        await arm_concept_questions_after_opening(
            handler_ctx, session, session_id, student_id, topic
        )
        await session.save()
        cc = (getattr(session, "current_concept", None) or "").strip()
        q = (getattr(session, "current_question", None) or "").strip()
        return {
            "type": "concept_question",
            "message": q
            or (
                f"Let's check your understanding of **{cc or 'this concept'}**. "
                "Answer the question in chat."
            ),
            "question": q or None,
            "current_concept": cc,
            "flow_state": "concept_questions",
        }

    async def _emit_story_hook_step(
        self, session: Session
    ) -> Optional[Dict[str, Any]]:
        """
        Emit the current Story Hook step, planning on first entry.

        Returns None when the stage has nothing left to say, in which case the
        caller moves the teaching sequence on.
        """
        snap = getattr(session, "concept_teaching_story_hook_snapshot", None)
        if not story_hook_has_content(snap):
            # Should not happen after resolve_effective — skip defensively
            self._advance_stage(session)
            return None

        concept = await self._resolve_current_concept(session)
        hook = normalize_story_hook(snap)
        label = self._concept_label(session, concept)
        language_mode = await resolve_mode_for_session(session)

        from app.services.pedagogy.teacher_voice import build_continuity_card

        plan = await story_hook_runtime.ensure_plan(
            session,
            concept=concept,
            hook=hook,
            concept_label=label,
            language_mode=language_mode,
            continuity=build_continuity_card(
                concept=concept,
                session=session,
                current_stage="story_hook",
                concept_name=label,
            ),
        )
        step = (
            story_hook_runtime.current_step(session, plan) if plan is not None else None
        )
        if plan is None or step is None:
            story_hook_runtime.mark_done(session)
            await session.save()
            return None

        story_hook_runtime.mark_emitted(session, step)
        await session.save()
        return story_hook_runtime.step_response(
            session,
            plan,
            step,
            concept_id=getattr(concept, "id", None),
            hook_title=str((snap or {}).get("title") or "").strip(),
            current_concept=(getattr(session, "current_concept", None) or "").strip(),
            flow_state=FLOW_STORY_HOOK,
        )

    async def _advance_story_hook(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
    ) -> Optional[Dict[str, Any]]:
        """Move to the next planned step, or finish the stage when none remain."""
        plan = plan_from_stored(getattr(session, "story_hook_plan", None))
        status = str(getattr(session, "story_hook_status", "") or "")
        if plan is None or status == story_hook_runtime.STATUS_IDLE:
            # Nothing was ever emitted (sticky FE action) — start the story
            # rather than silently skipping it.
            emitted = await self._emit_story_hook_step(session)
            if emitted is not None:
                return emitted
        else:
            expected_step = int(getattr(session, "story_hook_step_index", 0) or 0)
            sid = getattr(session, "id", None)
            coll = _session_collection() if sid is not None else None
            if coll is not None:
                from datetime import datetime

                claimed = await coll.find_one_and_update(
                    {
                        "_id": sid,
                        "story_hook_step_index": expected_step,
                        "flow_state": "concept_story_hook",
                    },
                    {
                        "$set": {
                            "story_hook_step_index": expected_step + 1,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )
                if claimed is None:
                    logger.info(
                        "[STORY_HOOK] step_claim_rejected session_id=%s expected_step=%s",
                        sid,
                        expected_step,
                    )
                    try:
                        from app.services.pedagogy.teaching_runtime_metrics import incr

                        incr("story_hook_step_rejected")
                    except Exception:
                        pass
                    return {"type": "noop", "message": ""}
                session.story_hook_step_index = expected_step + 1
            else:
                story_hook_runtime.advance_step(session)
            if not story_hook_runtime.plan_exhausted(session, plan):
                emitted = await self._emit_story_hook_step(session)
                if emitted is not None:
                    return emitted
            story_hook_runtime.mark_done(session)

        return await self._complete_story_hook(
            session,
            handler_ctx=handler_ctx,
            session_id=session_id,
            student_id=student_id,
            topic=topic,
        )

    async def _answer_story_hook_question(
        self, session: Session, student_answer: str
    ) -> Dict[str, Any]:
        """
        Reply to a Story Hook answer with a fresh LLM call.

        The reply is its own turn: the student sees it, then the usual advance
        action continues the story. The step pointer stays on the question so the
        advance moves exactly one step, as it does after narration.
        """
        plan = plan_from_stored(getattr(session, "story_hook_plan", None))
        concept = await self._resolve_current_concept(session)
        label = self._concept_label(session, concept)
        language_mode = story_hook_runtime.resolve_language_label(
            getattr(session, "story_hook_language", None)
        )

        reply = await story_hook_runtime.build_answer_reply(
            session,
            student_answer=student_answer,
            concept=concept,
            concept_label=label,
            language_mode=language_mode,
        )
        await session.save()

        index = int(getattr(session, "story_hook_step_index", 0) or 0)
        total = len(plan.steps) if plan is not None else 0
        snap = getattr(session, "concept_teaching_story_hook_snapshot", None)
        return story_hook_runtime.build_response(
            text=reply,
            kind="reply",
            index=index,
            total=total,
            last=plan is None or (index + 1) >= total,
            hook_title=str((snap or {}).get("title") or "").strip(),
            current_concept=(getattr(session, "current_concept", None) or "").strip(),
            flow_state=FLOW_STORY_HOOK,
        )

    async def _emit_visual_teaching_beat(
        self, session: Session
    ) -> Optional[Dict[str, Any]]:
        snap = getattr(session, "concept_teaching_visual_teaching_snapshot", None)
        if not visual_teaching_has_content(snap):
            self._advance_stage(session)
            return None

        concept = await self._resolve_current_concept(session)
        label = self._concept_label(session, concept)
        language_mode = await resolve_mode_for_session(session)
        language = getattr(language_mode, "value", None) or str(language_mode or "en")

        from app.services.pedagogy.teacher_voice import build_continuity_card

        plan = await visual_teaching_runtime.ensure_plan(
            session,
            authored_snapshot=snap,
            vtse_template=getattr(concept, "vtse_template", None) if concept else None,
            language=str(language),
            concept_name=label,
            continuity=build_continuity_card(
                concept=concept,
                session=session,
                current_stage="visual_teaching",
                concept_name=label,
            ),
        )
        if plan is None:
            visual_teaching_runtime.mark_done(session)
            await session.save()
            logger.warning(
                "[VISUAL_TEACHING] planner_failed_skip concept=%s",
                label,
            )
            return None

        concept_id = str(getattr(concept, "id", "") or "")
        playable = await visual_teaching_runtime.skip_to_next_playable_scene(
            session,
            plan,
            authored_snapshot=snap,
            concept_id=concept_id,
        )
        if not playable or visual_teaching_runtime.plan_exhausted(session, plan):
            visual_teaching_runtime.mark_done(session)
            await session.save()
            return None

        session.flow_state = FLOW_VISUAL_TEACHING
        await session.save()
        return visual_teaching_runtime.step_response(
            session,
            plan,
            concept_id=concept_id,
            authored_snapshot=snap,
        )

    async def _advance_visual_teaching(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
        action: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if visual_teaching_runtime.is_stage_done(session):
            return await self._complete_visual_teaching(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )

        plan = visual_teaching_runtime.plan_from_stored(
            getattr(session, "visual_teaching_plan", None)
        )
        status = str(getattr(session, "visual_teaching_status", "") or "")
        if plan is None or status in (
            visual_teaching_runtime.STATUS_IDLE,
            visual_teaching_runtime.STATUS_FAILED,
        ):
            emitted = await self._emit_visual_teaching_beat(session)
            if emitted is not None:
                return emitted
            return await self._complete_visual_teaching(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
            )

        parsed = visual_teaching_runtime.parse_advance_action(action)
        kind = "next"
        expected_s: Optional[int] = None
        expected_b: Optional[int] = None
        if parsed is not None:
            kind, expected_s, expected_b = parsed
        cur_s, cur_b, cur_sent = visual_teaching_runtime.current_cursor(session)
        if expected_s is None or expected_b is None:
            expected_s, expected_b = cur_s, cur_b

        # FE asked to advance a beat we already left → idempotent confirm.
        if visual_teaching_runtime.cursor_is_past(
            cur_scene=cur_s,
            cur_beat=cur_b,
            expected_scene=expected_s,
            expected_beat=expected_b,
        ):
            return visual_teaching_runtime.advance_ack(
                outcome="already_advanced",
                scene_index=cur_s,
                beat_index=cur_b,
                status=status,
                flow_state=str(getattr(session, "flow_state", "") or ""),
                sentence_index=cur_sent,
            )
        if cur_s != expected_s or cur_b != expected_b:
            return visual_teaching_runtime.advance_ack(
                outcome="stale",
                scene_index=cur_s,
                beat_index=cur_b,
                status=status,
                flow_state=str(getattr(session, "flow_state", "") or ""),
                sentence_index=cur_sent,
            )

        force_done = kind == "done"
        next_cursor = visual_teaching_runtime.compute_next_cursor(
            plan, expected_s, expected_b
        )
        snap = getattr(session, "concept_teaching_visual_teaching_snapshot", None)
        concept = await self._resolve_current_concept(session)
        concept_id = str(getattr(concept, "id", "") or "")
        sid = getattr(session, "id", None) or session_id

        if next_cursor is not None and not force_done:
            # Simulate skip-forward for missing binaries before the atomic write.
            from types import SimpleNamespace

            probe = SimpleNamespace(
                visual_teaching_scene_index=next_cursor[0],
                visual_teaching_beat_index=next_cursor[1],
                visual_teaching_sentence_index=-1,
                visual_teaching_skipped_scenes=list(
                    getattr(session, "visual_teaching_skipped_scenes", None) or []
                ),
                visual_teaching_status=visual_teaching_runtime.STATUS_PLAYING,
            )
            playable = await visual_teaching_runtime.skip_to_next_playable_scene(
                probe,
                plan,
                authored_snapshot=snap,
                concept_id=concept_id,
            )
            if playable:
                skipped_now = sorted(
                    set(probe.visual_teaching_skipped_scenes or [])
                    - set(
                        getattr(session, "visual_teaching_skipped_scenes", None)
                        or []
                    )
                )
                target_s = int(probe.visual_teaching_scene_index)
                target_b = int(probe.visual_teaching_beat_index)
                if sid is not None:
                    after = await visual_teaching_runtime.atomic_try_advance_from_beat(
                        sid,
                        expected_scene=expected_s,
                        expected_beat=expected_b,
                        next_scene=target_s,
                        next_beat=target_b,
                        skipped_scenes=skipped_now or None,
                    )
                    if after is None:
                        fresh = await Session.get(sid)
                        if fresh is not None:
                            visual_teaching_runtime.hydrate_vt_fields(
                                session,
                                {
                                    "visual_teaching_scene_index": fresh.visual_teaching_scene_index,
                                    "visual_teaching_beat_index": fresh.visual_teaching_beat_index,
                                    "visual_teaching_sentence_index": fresh.visual_teaching_sentence_index,
                                    "visual_teaching_status": fresh.visual_teaching_status,
                                    "visual_teaching_skipped_scenes": fresh.visual_teaching_skipped_scenes,
                                    "flow_state": fresh.flow_state,
                                },
                            )
                        fresh_s, fresh_b, fresh_sent = (
                            visual_teaching_runtime.current_cursor(session)
                        )
                        outcome: visual_teaching_runtime.AdvanceOutcome = (
                            "already_advanced"
                            if visual_teaching_runtime.cursor_is_past(
                                cur_scene=fresh_s,
                                cur_beat=fresh_b,
                                expected_scene=expected_s,
                                expected_beat=expected_b,
                            )
                            or visual_teaching_runtime.is_stage_done(session)
                            else "stale"
                        )
                        return visual_teaching_runtime.advance_ack(
                            outcome=outcome,
                            scene_index=fresh_s,
                            beat_index=fresh_b,
                            status=str(
                                getattr(session, "visual_teaching_status", "")
                                or ""
                            ),
                            flow_state=str(
                                getattr(session, "flow_state", "") or ""
                            ),
                            sentence_index=fresh_sent,
                        )
                    visual_teaching_runtime.hydrate_vt_fields(session, after)
                else:
                    session.visual_teaching_scene_index = target_s
                    session.visual_teaching_beat_index = target_b
                    session.visual_teaching_sentence_index = -1
                    if skipped_now:
                        session.visual_teaching_skipped_scenes = sorted(
                            set(
                                getattr(
                                    session, "visual_teaching_skipped_scenes", None
                                )
                                or []
                            )
                            | set(skipped_now)
                        )
                    await session.save()
                return visual_teaching_runtime.step_response(
                    session,
                    plan,
                    concept_id=concept_id,
                    authored_snapshot=snap,
                )

        return await self._complete_visual_teaching(
            session,
            handler_ctx=handler_ctx,
            session_id=session_id,
            student_id=student_id,
            topic=topic,
            expected_scene=expected_s,
            expected_beat=expected_b,
        )

    async def _complete_visual_teaching(
        self,
        session: Session,
        *,
        handler_ctx: Any,
        session_id: Optional[PydanticObjectId],
        student_id: Optional[PydanticObjectId],
        topic: Any,
        expected_scene: Optional[int] = None,
        expected_beat: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        seq = list(getattr(session, "concept_teaching_sequence_snapshot", None) or [])
        idx = int(getattr(session, "concept_teaching_stage_index", 0) or 0)
        already_past = True
        if idx < len(seq) and seq[idx] == "visual_teaching":
            already_past = False
        elif "visual_teaching" in seq:
            try:
                already_past = idx > seq.index("visual_teaching")
            except ValueError:
                already_past = True

        status = str(getattr(session, "visual_teaching_status", "") or "")
        flow = str(getattr(session, "flow_state", "") or "")
        if already_past and status == visual_teaching_runtime.STATUS_DONE:
            return {"type": "noop"}

        new_stage: Optional[int] = None
        if idx < len(seq) and seq[idx] == "visual_teaching":
            new_stage = idx + 1
        elif "visual_teaching" in seq and not already_past:
            try:
                new_stage = seq.index("visual_teaching") + 1
            except ValueError:
                new_stage = None

        sid = getattr(session, "id", None) or session_id
        claimed = None
        peek_next = self._peek_executable_from(session, new_stage)
        claim_vtse = peek_next == "vtse"
        c_idx = vtse_opening_claim.concept_index(session)
        if sid is not None and flow == FLOW_VISUAL_TEACHING:
            claimed = await visual_teaching_runtime.atomic_claim_leave_visual_teaching(
                sid,
                expected_scene=expected_scene,
                expected_beat=expected_beat,
                new_stage_index=new_stage,
                claim_vtse_opening=claim_vtse,
                concept_index=c_idx if claim_vtse else None,
            )
            if claimed is None:
                # Another worker already left VT — never fall through to idle re-open.
                return self._vt_done_advance_ack(session)
            hydrate: Dict[str, Any] = {
                "flow_state": (
                    FLOW_VTSE_OPENING if claim_vtse else "idle"
                ),
                "visual_teaching_status": visual_teaching_runtime.STATUS_DONE,
            }
            if new_stage is not None:
                hydrate["concept_teaching_stage_index"] = new_stage
            visual_teaching_runtime.hydrate_vt_fields(session, hydrate)
            if claim_vtse:
                vtse_opening_claim.hydrate_opening_fields(
                    session,
                    {
                        "concept_vtse_opening_status": vtse_opening_claim.VTSE_OPENING_STARTING,
                        "concept_vtse_opening_for_index": c_idx,
                        "flow_state": FLOW_VTSE_OPENING,
                    },
                )
        else:
            # Fixture / non-persisted path.
            if new_stage is not None:
                session.concept_teaching_stage_index = new_stage
            visual_teaching_runtime.mark_done(session)
            if claim_vtse:
                session.flow_state = FLOW_VTSE_OPENING
                session.concept_vtse_opening_status = (
                    vtse_opening_claim.VTSE_OPENING_STARTING
                )
                session.concept_vtse_opening_for_index = c_idx
            else:
                session.flow_state = "idle"
            await session.save()

        next_stage = self._skip_non_executable_stages(session)
        if next_stage == "vtse":
            return await self._start_vtse_after_hook(
                session,
                handler_ctx=handler_ctx,
                session_id=session_id,
                student_id=student_id,
                topic=topic,
                opening_already_claimed=claim_vtse,
            )
        if next_stage == "story_hook":
            emitted = await self._emit_story_hook_step(session)
            if emitted is not None:
                return emitted
        if next_stage == "visual_teaching":
            emitted = await self._emit_visual_teaching_beat(session)
            if emitted is not None:
                return emitted
        return await self._arm_post_concept_questions(
            session,
            handler_ctx=handler_ctx,
            session_id=session_id,
            student_id=student_id,
            topic=topic,
        )

    @staticmethod
    def _concept_label(session: Session, concept: Any) -> str:
        label = str(getattr(concept, "display_name", "") or "").strip()
        if label:
            return label
        return (getattr(session, "current_concept", None) or "").strip()

    async def apply_flow_state(self, session: Session, result: Dict[str, Any]) -> None:
        fs = result.get("flow_state")
        if not fs:
            return
        session.flow_state = str(fs)
        sid = getattr(session, "id", None)
        coll = _session_collection() if sid is not None else None
        if coll is not None:
            try:
                from datetime import datetime

                await coll.update_one(
                    {"_id": sid},
                    {"$set": {"flow_state": str(fs), "updated_at": datetime.utcnow()}},
                )
                return
            except Exception:
                logger.exception("[CONCEPT_TEACH] apply_flow_state_narrow_failed")
        await session.save()

    async def _resolve_current_concept(
        self, session: Session
    ) -> Optional[CurriculumConcept]:
        ids = list(getattr(session, "key_concept_ids", None) or [])
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        if idx < 0 or idx >= len(ids):
            return None
        concept_id = ids[idx]
        try:
            return await self._concepts.get_by_id(concept_id)
        except Exception:  # noqa: BLE001
            logger.exception("[CONCEPT_TEACH] resolve_concept_failed")
            return None
