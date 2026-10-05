"""Zone transition gate — Clarity Gate runs when current_zone != target_zone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.learning.sessions import Session
from app.models.progression.student_plan_progress import StudentPlanProgress
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.student_plan_progress_repository import StudentPlanProgressRepository
from app.services.handlers.cluster_utils import derive_current_cluster_index, resolve_clusters
from app.services.progression.plan_session_cluster_registry import (
    AssignedCluster,
    PlanSessionClusterRegistry,
)
from app.services.progression.session_unlock_engine import SessionUnlockEngine


@dataclass(frozen=True)
class ZoneTransitionDecision:
    """Whether and how to run the zone transition gate."""

    needs_gate: bool
    from_zone: int
    target_zone: int
    complete_session_after_gate: bool
    gate_concepts: tuple[str, ...]
    gate_message: str


@dataclass(frozen=True)
class ZoneEntryResult:
    response_type: str
    message: str
    target_zone: int
    complete_session: bool


def _first_zone_for_plan(plan: ClassSessionPlan) -> int:
    return PlanSessionClusterRegistry.first_zone_number(plan)


def _zones_in_plan(plan: ClassSessionPlan) -> set[int]:
    return {
        int(row.zone_number)
        for row in PlanSessionClusterRegistry.assigned_clusters(plan)
    }


def _concepts_for_zone_clusters(
    session: Session,
    plan: ClassSessionPlan,
    zone_number: int,
) -> list[str]:
    kc = [str(c).strip() for c in (getattr(session, "key_concepts", None) or []) if str(c).strip()]
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    assigned = PlanSessionClusterRegistry.assigned_clusters(plan)
    by_id = {row.curriculum_cluster_id: row for row in assigned}
    out: list[str] = []
    seen: set[str] = set()
    for row in assigned:
        if int(row.zone_number) != int(zone_number):
            continue
        if row.cluster_index >= len(clusters):
            continue
        for concept in clusters[row.cluster_index]:
            key = str(concept).strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                out.append(key)
    if out:
        return out
    taught = [
        str(p).strip()
        for p in (getattr(session, "topic_taught_points", None) or [])
        if str(p).strip()
    ]
    return taught or kc


def _zone_for_concept_index(session: Session, plan: ClassSessionPlan, concept_index: int) -> int:
    kc = list(session.key_concepts or [])
    clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
    cluster_index = derive_current_cluster_index(int(concept_index or 0), clusters)
    assigned = PlanSessionClusterRegistry.assigned_clusters(plan)
    for row in assigned:
        if row.cluster_index == cluster_index:
            return int(row.zone_number)
    return int(getattr(session, "current_zone", 1) or 1)


class ZoneTransitionCoordinator:
    """Decides when Clarity Gate runs and what happens after it passes."""

    @staticmethod
    def parse_zone_entry_flow(flow_state: str | None) -> int | None:
        fs = str(flow_state or "").strip().lower()
        # Zone 2 uses the same VTSE engine as Zone 1 — only 3+ are entry stubs.
        for zone in (3, 4):
            if fs == f"zone_{zone}_entry":
                return zone
        return None

    @staticmethod
    def zone_entry_payload(zone: int) -> dict[str, Any]:
        zone = int(zone)
        return {
            "type": f"zone_{zone}_entry_ready",
            "message": (
                f"Zone {zone} is ready. "
                f"(Zone {zone} teaching will be built in a future release.)"
            ),
            "target_zone": zone,
            "correct": True,
        }

    def enter_zone_entry_stub(self, session: Session, zone: int) -> None:
        """Park runtime in a Zone 2–4 entry stub — no Zone 1 VTSE."""
        zone = int(zone)
        session.current_zone = zone
        session.flow_state = f"zone_{zone}_entry"
        session.learning_state = "explaining"
        session.current_mode = "normal"
        session.current_question = None
        session.cluster_teachback_active = False
        session.cluster_quiz_active = False
        session.concept_questions_active = False

    def __init__(
        self,
        plan_repo: ClassSessionPlanRepository | None = None,
        progress_repo: StudentPlanProgressRepository | None = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._progress = progress_repo or StudentPlanProgressRepository()
        self._unlock = SessionUnlockEngine(plan_repo=self._plans)

    async def load_progress(self, session: Session) -> StudentPlanProgress | None:
        track_key = str(getattr(session, "progression_track_key", None) or "").strip()
        if not track_key:
            return None
        return await self._progress.get_by_track(session.student_id, track_key)

    async def load_plan(self, session: Session) -> ClassSessionPlan | None:
        plan_id = getattr(session, "progression_session_plan_id", None)
        if plan_id is None:
            return None
        return await self._plans.get_by_id(plan_id)

    async def decide_after_cluster_teachback(
        self,
        session: Session,
        *,
        topic_done: bool,
        progress: StudentPlanProgress | None = None,
    ) -> ZoneTransitionDecision:
        plan = await self.load_plan(session)
        if plan is None:
            raise ValueError(
                "Structured session planning is required; progression_session_plan_id is missing"
            )

        from_zone = int(getattr(session, "current_zone", 1) or 1)
        new_idx = int(getattr(session, "current_concept_index", 0) or 0)

        if not topic_done:
            target_zone = _zone_for_concept_index(session, plan, new_idx)
            if target_zone == from_zone:
                return ZoneTransitionDecision(
                    needs_gate=False,
                    from_zone=from_zone,
                    target_zone=from_zone,
                    complete_session_after_gate=False,
                    gate_concepts=(),
                    gate_message="",
                )
            concepts = _concepts_for_zone_clusters(session, plan, from_zone)
            return ZoneTransitionDecision(
                needs_gate=True,
                from_zone=from_zone,
                target_zone=target_zone,
                complete_session_after_gate=False,
                gate_concepts=tuple(concepts),
                gate_message=(
                    f"Before we move into Zone {target_zone}, walk me through what "
                    f"you learned in Zone {from_zone} — connect the main ideas in "
                    "your own words."
                ),
            )

        # Session slice complete — gate before session end if next zone differs.
        if progress is None:
            progress = await self.load_progress(session)
        target_zone = await self._next_zone_after_session_slice(
            session, plan, progress=progress
        )
        if target_zone is None or target_zone == from_zone:
            return ZoneTransitionDecision(
                needs_gate=False,
                from_zone=from_zone,
                target_zone=from_zone,
                complete_session_after_gate=True,
                gate_concepts=(),
                gate_message="",
            )

        concepts = _concepts_for_zone_clusters(session, plan, from_zone)
        if not concepts:
            kc = [str(c).strip() for c in (getattr(session, "key_concepts", None) or []) if str(c).strip()]
            concepts = kc
        return ZoneTransitionDecision(
            needs_gate=True,
            from_zone=from_zone,
            target_zone=target_zone,
            complete_session_after_gate=True,
            gate_concepts=tuple(concepts),
            gate_message=(
                f"Before we finish this session, explain how the Zone {from_zone} "
                f"ideas fit together — then we'll be ready for Zone {target_zone}."
            ),
        )

    async def _next_zone_after_session_slice(
        self,
        session: Session,
        plan: ClassSessionPlan,
        *,
        progress: StudentPlanProgress | None,
    ) -> Optional[int]:
        zones_here = _zones_in_plan(plan)
        from_zone = int(getattr(session, "current_zone", 1) or 1)
        higher_in_session = [z for z in zones_here if z > from_zone]
        if higher_in_session:
            return min(higher_in_session)

        if progress is None:
            return None

        ordered = await self._unlock.list_ordered_plans(progress)
        seq = int(plan.sequence_number)
        next_plan = next((p for p in ordered if int(p.sequence_number) == seq + 1), None)
        if next_plan is None:
            return None
        return _first_zone_for_plan(next_plan)

    def stage_gate(
        self,
        session: Session,
        decision: ZoneTransitionDecision,
    ) -> None:
        """Queue zone transition gate — cluster teachback LLM reply shows first."""
        session.zone_transition_gate_pending = True
        session.zone_transition_from_zone = decision.from_zone
        session.zone_transition_target_zone = decision.target_zone
        session.zone_transition_complete_session = decision.complete_session_after_gate
        session.clarity_gate_concepts = list(decision.gate_concepts)
        session.clarity_gate_question = decision.gate_message
        session.clarity_gate_active = False
        session.clarity_gate_step = None
        session.clarity_sus_retry_done = False

    def activate_pending_gate(self, session: Session) -> dict[str, Any]:
        """Open a staged zone transition gate after cluster teachback feedback."""
        if not bool(getattr(session, "zone_transition_gate_pending", False)):
            return {"type": "noop"}
        decision = ZoneTransitionDecision(
            needs_gate=True,
            from_zone=int(getattr(session, "zone_transition_from_zone", 1) or 1),
            target_zone=int(
                getattr(session, "zone_transition_target_zone", None)
                or getattr(session, "current_zone", 1)
                or 1
            ),
            complete_session_after_gate=bool(
                getattr(session, "zone_transition_complete_session", False)
            ),
            gate_concepts=tuple(
                str(c).strip()
                for c in (getattr(session, "clarity_gate_concepts", None) or [])
                if str(c).strip()
            ),
            gate_message=str(
                getattr(session, "clarity_gate_question", None)
                or "Explain how the main ideas from this zone fit together."
            ),
        )
        session.zone_transition_gate_pending = False
        return self.begin_gate(session, decision)

    def begin_gate(
        self,
        session: Session,
        decision: ZoneTransitionDecision,
    ) -> dict[str, Any]:
        session.zone_transition_from_zone = decision.from_zone
        session.zone_transition_target_zone = decision.target_zone
        session.zone_transition_complete_session = decision.complete_session_after_gate
        session.flow_state = "teachback"
        session.current_mode = "teachback"
        session.learning_state = "explaining"
        session.clarity_gate_active = True
        session.clarity_gate_step = 0
        session.clarity_gate_concepts = list(decision.gate_concepts)
        session.clarity_gate_question = decision.gate_message
        session.clarity_sus_retry_done = False
        session.zone_transition_gate_pending = False
        return {
            "type": "clarity_gate_start",
            "message": decision.gate_message,
            "correct": True,
            "clarity_gate": True,
            "gate_concepts": list(decision.gate_concepts),
            "zone_transition": True,
            "from_zone": decision.from_zone,
            "target_zone": decision.target_zone,
        }

    def complete_gate(self, session: Session) -> ZoneEntryResult:
        target = int(
            getattr(session, "zone_transition_target_zone", None)
            or getattr(session, "current_zone", 1)
            or 1
        )
        complete_session = bool(getattr(session, "zone_transition_complete_session", False))

        session.clarity_gate_active = False
        session.clarity_gate_step = None
        session.clarity_gate_concepts = None
        session.clarity_gate_question = None
        session.clarity_sus_retry_done = False
        session.zone_transition_gate_pending = False
        session.zone_transition_from_zone = None
        session.zone_transition_target_zone = None
        session.zone_transition_complete_session = False
        session.current_zone = target
        session.current_mode = "normal"
        session.zone_round_successes = 0

        if complete_session:
            session.flow_state = "completed"
            session.current_question = None
            return ZoneEntryResult(
                response_type="completed",
                message=(
                    f"Excellent work in Zone {target - 1 if target > 1 else 1}! "
                    "You've completed this session. 🌟"
                ),
                target_zone=target,
                complete_session=True,
            )

        if target in (1, 2):
            session.flow_state = "idle"
            session.learning_state = "explaining"
            idx = int(getattr(session, "current_concept_index", 0) or 0)
            kc = [
                str(c).strip()
                for c in (getattr(session, "key_concepts", None) or [])
                if str(c).strip()
            ]
            if idx < len(kc):
                session.current_concept = kc[idx][:500]
            return ZoneEntryResult(
                response_type="teachback_passed",
                message=f"Zone {target} — let's continue.",
                target_zone=target,
                complete_session=False,
            )

        self.enter_zone_entry_stub(session, target)
        if target == 3:
            placeholder = "Zone 3 is not implemented yet."
        else:
            placeholder = (
                f"Zone {target} is ready. "
                f"(Zone {target} teaching will be built in a future release.)"
            )
        return ZoneEntryResult(
            response_type=f"zone_{target}_entry_ready",
            message=placeholder,
            target_zone=target,
            complete_session=False,
        )

    async def sync_current_zone_for_index(self, session: Session) -> None:
        """Align ``current_zone`` with the plan zone for ``current_concept_index``."""
        plan = await self.load_plan(session)
        if plan is None:
            return
        idx = int(getattr(session, "current_concept_index", 0) or 0)
        session.current_zone = _zone_for_concept_index(session, plan, idx)

    async def resolve_after_teachback_slice(
        self,
        session: Session,
        *,
        topic_done: bool,
        default_complete_message: str,
        defer_gate_start: bool = False,
    ) -> dict[str, Any]:
        """Return a tutor payload after cluster/concept teachback, or ``_continue``."""
        try:
            decision = await self.decide_after_cluster_teachback(
                session,
                topic_done=topic_done,
            )
        except ValueError:
            if topic_done:
                session.flow_state = "completed"
                session.current_mode = "normal"
                session.learning_state = "explaining"
                session.clarity_gate_active = False
                session.clarity_gate_step = None
                session.clarity_gate_concepts = None
                session.clarity_gate_question = None
                session.zone_transition_gate_pending = False
                session.current_concept = None
                return {"type": "completed", "message": default_complete_message}
            return {"type": "_continue"}

        if decision.needs_gate:
            if defer_gate_start:
                if not topic_done:
                    session.current_concept = None
                self.stage_gate(session, decision)
                return {"type": "_defer_gate"}
            if not topic_done:
                session.current_concept = None
            return self.begin_gate(session, decision)

        if topic_done:
            session.flow_state = "completed"
            session.current_mode = "normal"
            session.learning_state = "explaining"
            session.clarity_gate_active = False
            session.clarity_gate_step = None
            session.clarity_gate_concepts = None
            session.clarity_gate_question = None
            session.zone_transition_gate_pending = False
            session.current_concept = None
            return {"type": "completed", "message": default_complete_message}
        return {"type": "_continue"}

    @staticmethod
    def response_from_entry_result(
        result: ZoneEntryResult,
        *,
        coverage: float | None = None,
        depth: float | None = None,
        missing: list[str] | None = None,
        graceful_exit: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": result.response_type,
            "message": result.message,
            "target_zone": result.target_zone,
        }
        if coverage is not None:
            payload["coverage_score"] = coverage
        if depth is not None:
            payload["depth_score"] = depth
        if missing:
            payload["missing_concepts"] = missing
        if graceful_exit and result.response_type not in ("completed",):
            missing_str = (
                ", ".join(f'"{c}"' for c in (missing or [])[:3])
                if missing
                else "some areas"
            )
            payload["type"] = "clarity_gate_exit"
            payload["message"] = (
                f"Good effort! We'll continue — just keep {missing_str} in mind "
                f"as we move forward. Practice makes perfect! 💪"
            )
        elif result.response_type in (
            "teachback_passed",
            "zone_2_entry_ready",
            "zone_3_entry_ready",
            "zone_4_entry_ready",
        ):
            payload["correct"] = True
        return payload
