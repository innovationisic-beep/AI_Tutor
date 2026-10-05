from __future__ import annotations

from typing import Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.learning.sessions import Session
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry


class PlanSessionClusterRegistryExt(PlanSessionClusterRegistry):
    @staticmethod
    async def cluster_id_for_session_cluster_index(
        session: Session,
        cluster_index: int,
        *,
        plan_repo: Optional[ClassSessionPlanRepository] = None,
    ) -> Optional[PydanticObjectId]:
        plan_id = getattr(session, "progression_session_plan_id", None)
        if plan_id is None:
            return None
        repo = plan_repo or ClassSessionPlanRepository()
        plan = await repo.get_by_id(plan_id)
        if plan is None:
            return None
        return PlanSessionClusterRegistry.cluster_id_for_index(plan, cluster_index)
