from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.progression.student_plan_progress import StudentPlanProgress
from app.services.progression.plan_session_cluster_registry import (
    AssignedCluster,
    PlanSessionClusterRegistry,
)


@dataclass
class SessionCompletionResult:
    is_complete: bool
    assigned_cluster_count: int
    completed_cluster_count: int
    missing_cluster_ids: List[PydanticObjectId]


class SessionCompletionEngine:
    """Session completes when ALL assigned clusters for the plan are complete."""

    def __init__(self) -> None:
        self._registry = PlanSessionClusterRegistry()

    def assigned_clusters(self, plan: ClassSessionPlan) -> List[AssignedCluster]:
        return self._registry.assigned_clusters(plan)

    def completed_ids_for_session(
        self, progress: StudentPlanProgress, session_plan_id: PydanticObjectId
    ) -> List[PydanticObjectId]:
        key = str(session_plan_id)
        raw = progress.completed_clusters_by_session.get(key) or []
        out: List[PydanticObjectId] = []
        for item in raw:
            try:
                out.append(PydanticObjectId(str(item)))
            except Exception:
                continue
        return out

    def evaluate(
        self,
        progress: StudentPlanProgress,
        plan: ClassSessionPlan,
    ) -> SessionCompletionResult:
        assigned = self.assigned_clusters(plan)
        if not assigned:
            return SessionCompletionResult(
                is_complete=False,
                assigned_cluster_count=0,
                completed_cluster_count=0,
                missing_cluster_ids=[],
            )

        done = set(self.completed_ids_for_session(progress, plan.id))
        missing = [row.curriculum_cluster_id for row in assigned if row.curriculum_cluster_id not in done]
        return SessionCompletionResult(
            is_complete=len(missing) == 0,
            assigned_cluster_count=len(assigned),
            completed_cluster_count=len(assigned) - len(missing),
            missing_cluster_ids=missing,
        )

    def record_cluster_complete(
        self,
        progress: StudentPlanProgress,
        *,
        session_plan_id: PydanticObjectId,
        cluster_id: PydanticObjectId,
    ) -> None:
        key = str(session_plan_id)
        bucket = list(progress.completed_clusters_by_session.get(key) or [])
        cid = str(cluster_id)
        if cid not in bucket:
            bucket.append(cid)
        progress.completed_clusters_by_session[key] = bucket

        if cluster_id not in progress.completed_cluster_ids:
            progress.completed_cluster_ids.append(cluster_id)

    def update_completion_percentage(
        self,
        progress: StudentPlanProgress,
        *,
        ordered_plans: List[ClassSessionPlan],
    ) -> None:
        if not ordered_plans:
            progress.completion_percentage = 0.0
            return
        total_sessions = len(ordered_plans)
        completed_sessions = len(progress.completed_session_plan_ids)
        current_plan = next(
            (p for p in ordered_plans if p.id == progress.current_session_plan_id),
            None,
        )
        session_fraction = 0.0
        if current_plan is not None and current_plan.id not in progress.completed_session_plan_ids:
            result = self.evaluate(progress, current_plan)
            if result.assigned_cluster_count > 0:
                session_fraction = (
                    result.completed_cluster_count / result.assigned_cluster_count
                ) / total_sessions

        progress.completion_percentage = min(
            100.0,
            round(
                ((completed_sessions / total_sessions) + session_fraction) * 100.0,
                2,
            ),
        )
