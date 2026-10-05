from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.progression.student_plan_progress import StudentPlanProgress
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry
from app.services.progression.release_policy import ImmediateReleasePolicy, ReleasePolicy


@dataclass
class UnlockResult:
    unlocked_plan_id: Optional[PydanticObjectId]
    auto_start_plan: Optional[ClassSessionPlan]
    transition_title: Optional[str] = None
    transition_subtitle: Optional[str] = None


class SessionUnlockEngine:
    def __init__(
        self,
        plan_repo: ClassSessionPlanRepository | None = None,
        release_policy: ReleasePolicy | None = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._policy = release_policy or ImmediateReleasePolicy()

    async def list_ordered_plans(
        self, progress: StudentPlanProgress
    ) -> List[ClassSessionPlan]:
        if progress.plan_scope == "catalog" and progress.catalog_topic_id:
            return await self._plans.list_for_catalog_topic(
                catalog_topic_id=progress.catalog_topic_id,
                status="published",
            )
        if progress.teacher_topic_id:
            return await self._plans.list_for_topic_class(
                organization_id=progress.organization_id,
                teacher_topic_id=progress.teacher_topic_id,
                class_id=progress.class_id,
                status="published",
            )
        return []

    def _next_plan(
        self,
        ordered: List[ClassSessionPlan],
        current_plan_id: Optional[PydanticObjectId],
    ) -> Optional[ClassSessionPlan]:
        if not ordered:
            return None
        if current_plan_id is None:
            return ordered[0]
        for i, plan in enumerate(ordered):
            if plan.id == current_plan_id and i + 1 < len(ordered):
                return ordered[i + 1]
        return None

    async def on_session_completed(
        self,
        progress: StudentPlanProgress,
        *,
        completed_plan_id: PydanticObjectId,
    ) -> UnlockResult:
        ordered = await self.list_ordered_plans(progress)
        if completed_plan_id not in progress.completed_session_plan_ids:
            progress.completed_session_plan_ids.append(completed_plan_id)

        next_plan = self._next_plan(ordered, completed_plan_id)
        if next_plan is None:
            progress.status = "completed"
            progress.completed_at = datetime.utcnow()
            progress.current_session_plan_id = None
            progress.last_transition = {
                "kind": "track_completed",
                "title": "All sessions completed",
                "subtitle": "You finished the full learning plan.",
            }
            return UnlockResult(None, None, "All sessions completed", "")

        available_at = self._policy.release_at(completed_at=datetime.utcnow())
        if not self._policy.is_available_now(available_at=available_at):
            return UnlockResult(next_plan.id, None)

        if next_plan.id not in progress.unlocked_session_plan_ids:
            progress.unlocked_session_plan_ids.append(next_plan.id)

        progress.current_session_plan_id = next_plan.id
        auto_start = next_plan if self._policy.should_auto_start() else None

        first_zone = PlanSessionClusterRegistry.first_zone_number(next_plan)
        zone_label = f"Zone {first_zone}"
        cluster_label = next_plan.title
        assigned = next_plan.items[0].display_name_snapshot if next_plan.items else cluster_label
        subtitle = f"{zone_label} • {assigned or cluster_label}"

        progress.last_transition = {
            "kind": "session_started",
            "title": f"SESSION {next_plan.sequence_number} STARTED",
            "subtitle": subtitle,
            "session_plan_id": str(next_plan.id),
            "sequence_number": next_plan.sequence_number,
        }

        return UnlockResult(
            next_plan.id,
            auto_start,
            f"SESSION {next_plan.sequence_number} STARTED",
            subtitle,
        )

    def learning_path_snapshot(
        self,
        progress: StudentPlanProgress,
        ordered: List[ClassSessionPlan],
    ) -> List[dict]:
        rows: List[dict] = []
        for plan in ordered:
            pid = plan.id
            if pid == progress.current_session_plan_id:
                state = "active"
            elif pid in progress.completed_session_plan_ids:
                state = "completed"
            elif pid in progress.unlocked_session_plan_ids:
                state = "available"
            else:
                state = "locked"
            rows.append(
                {
                    "session_plan_id": str(pid),
                    "sequence_number": plan.sequence_number,
                    "title": plan.title,
                    "state": state,
                }
            )
        return rows
