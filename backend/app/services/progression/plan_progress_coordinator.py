from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.learning.sessions import Session
from app.models.progression.student_plan_progress import ResumePointer, StudentPlanProgress
from app.models.runtime.runtime_curriculum_manifest import LaunchContext, RuntimeCurriculumManifest
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.student_plan_progress_repository import StudentPlanProgressRepository
from app.services.progression.cluster_completion_evaluator import ClusterCompletionEvaluator
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry
from app.services.progression.plan_session_cluster_registry_ext import (
    PlanSessionClusterRegistryExt,
)
from app.services.progression.release_policy import ImmediateReleasePolicy, ReleasePolicy
from app.services.progression.plan_session_cluster_registry import PlanSessionClusterRegistry
from app.services.progression.session_completion_engine import SessionCompletionEngine
from app.services.progression.session_unlock_engine import SessionUnlockEngine
from app.services.progression.zone_transition_coordinator import ZoneTransitionCoordinator


def build_plan_track_key(
    *,
    launch: LaunchContext,
    class_id: str = "",
) -> Optional[str]:
    if launch.class_session_plan_id is None and launch.resolution_mode not in (
        "catalog_session_plan",
        "class_session_full",
        "class_session_item",
    ):
        return None
    if launch.topic_source == "catalog" or launch.resolution_mode == "catalog_session_plan":
        return f"catalog:{launch.source_topic_id}"
    cid = (launch.class_id or class_id or "").strip()
    return f"teacher:{launch.source_topic_id}:{cid}"


class PlanProgressCoordinator:
    """Orchestrates plan/session/cluster progression without modifying Zone 1 handlers."""

    def __init__(
        self,
        progress_repo: StudentPlanProgressRepository | None = None,
        plan_repo: ClassSessionPlanRepository | None = None,
        release_policy: ReleasePolicy | None = None,
    ) -> None:
        self._progress = progress_repo or StudentPlanProgressRepository()
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._cluster_eval = ClusterCompletionEvaluator()
        self._session_engine = SessionCompletionEngine()
        self._unlock = SessionUnlockEngine(
            plan_repo=self._plans,
            release_policy=release_policy or ImmediateReleasePolicy(),
        )

    async def _list_plans_for_launch(
        self,
        *,
        launch: LaunchContext,
        organization_id: PydanticObjectId,
        class_id: str,
    ) -> List[ClassSessionPlan]:
        if launch.topic_source == "catalog" or launch.resolution_mode == "catalog_session_plan":
            return await self._plans.list_for_catalog_topic(
                catalog_topic_id=launch.source_topic_id,
                status="published",
            )
        return await self._plans.list_for_topic_class(
            organization_id=organization_id,
            teacher_topic_id=launch.source_topic_id,
            class_id=class_id,
            status="published",
        )

    async def ensure_on_session_start(
        self,
        session: Session,
        *,
        manifest: Optional[RuntimeCurriculumManifest],
    ) -> Optional[StudentPlanProgress]:
        if manifest is None:
            return None
        launch = manifest.launch_context
        track_key = build_plan_track_key(
            launch=launch,
            class_id=(getattr(session, "curriculum_class_id", None) or ""),
        )
        if not track_key or launch.class_session_plan_id is None:
            return None

        plan_id = launch.class_session_plan_id
        progress = await self._progress.get_by_track(session.student_id, track_key)
        now = datetime.utcnow()
        class_id = (launch.class_id or getattr(session, "curriculum_class_id", None) or "")

        if progress is None:
            ordered = await self._list_plans_for_launch(
                launch=launch,
                organization_id=session.organization_id,
                class_id=class_id,
            )
            first_id = ordered[0].id if ordered else plan_id
            unlocked_ids = [first_id]
            if plan_id not in unlocked_ids:
                unlocked_ids.append(plan_id)

            progress = StudentPlanProgress(
                student_id=session.student_id,
                organization_id=session.organization_id,
                plan_track_key=track_key,
                topic_id=session.topic_id,
                topic_source=launch.topic_source,
                plan_scope="catalog" if track_key.startswith("catalog:") else "teacher",
                catalog_topic_id=launch.source_topic_id
                if launch.topic_source == "catalog"
                else None,
                teacher_topic_id=launch.source_topic_id
                if launch.topic_source == "teacher"
                else None,
                class_id=class_id,
                subject_id=(launch.subject_id or getattr(session, "curriculum_subject_id", None) or ""),
                current_session_plan_id=plan_id,
                unlocked_session_plan_ids=unlocked_ids,
                status="in_progress",
                started_at=now,
                updated_at=now,
            )
            progress = await self._progress.create(progress)
        else:
            if plan_id not in progress.unlocked_session_plan_ids:
                progress.unlocked_session_plan_ids.append(plan_id)
            progress.current_session_plan_id = plan_id
            progress.status = "in_progress"
            progress.updated_at = now

        plan = await self._plans.get_by_id(plan_id)
        ordered = await self._unlock.list_ordered_plans(progress)
        if plan is not None:
            self._realign_progress_on_plan_start(progress, plan, ordered)

        await self._sync_resume_pointer(progress, session, plan_id)
        self._session_engine.update_completion_percentage(progress, ordered_plans=ordered)
        await self._progress.save(progress)

        session.progression_track_key = track_key
        session.progression_session_plan_id = plan_id
        if launch.class_session_instance_id:
            session.progression_class_instance_id = launch.class_session_instance_id

        if plan is not None and int(plan.sequence_number) > 1:
            session.zone0_phase = "done"
            session.zone0_prereq_done = True
            session.zone0_curiosity_shown = True
            first_zone = PlanSessionClusterRegistry.first_zone_number(plan)
            session.current_zone = first_zone
            if first_zone >= 3:
                ZoneTransitionCoordinator().enter_zone_entry_stub(session, first_zone)
            else:
                session.flow_state = "idle"

        await session.save()
        return progress

    def _realign_progress_on_plan_start(
        self,
        progress: StudentPlanProgress,
        plan: ClassSessionPlan,
        ordered: List[ClassSessionPlan],
    ) -> None:
        """Starting a plan slice rewinds completion for that session and later ones."""
        seq = int(plan.sequence_number)
        rewind_ids = {
            p.id for p in ordered if int(p.sequence_number) >= seq
        }
        if not rewind_ids:
            return

        progress.completed_session_plan_ids = [
            pid
            for pid in progress.completed_session_plan_ids
            if pid not in rewind_ids
        ]
        for pid in rewind_ids:
            progress.completed_clusters_by_session.pop(str(pid), None)

        progress.current_session_plan_id = plan.id
        if plan.id not in progress.unlocked_session_plan_ids:
            progress.unlocked_session_plan_ids.append(plan.id)
        progress.unlocked_session_plan_ids = [
            pid
            for pid in progress.unlocked_session_plan_ids
            if pid not in rewind_ids or pid == plan.id
        ]

    async def reconcile_progress_on_restore(self, session: Session) -> None:
        """Fix stale plan chips when reloading an opening (zone 0) session slice."""
        track_key = getattr(session, "progression_track_key", None)
        plan_id = getattr(session, "progression_session_plan_id", None)
        if not track_key or plan_id is None:
            return
        if int(getattr(session, "current_zone", 0) or 0) != 0:
            return
        if str(getattr(session, "zone0_phase", "") or "").lower() == "done":
            return

        progress = await self._progress.get_by_track(session.student_id, track_key)
        if progress is None:
            return
        if plan_id not in progress.completed_session_plan_ids:
            return

        plan = await self._plans.get_by_id(plan_id)
        if plan is None:
            return
        ordered = await self._unlock.list_ordered_plans(progress)
        self._realign_progress_on_plan_start(progress, plan, ordered)
        self._session_engine.update_completion_percentage(
            progress, ordered_plans=ordered
        )
        progress.updated_at = datetime.utcnow()
        await self._progress.save(progress)

    async def _sync_resume_pointer(
        self,
        progress: StudentPlanProgress,
        session: Session,
        plan_id: PydanticObjectId,
    ) -> None:
        cluster_index = int(getattr(session, "current_cluster_index", 0) or 0)
        concept_index = int(getattr(session, "current_concept_index", 0) or 0)
        cluster_id = await PlanSessionClusterRegistryExt.cluster_id_for_session_cluster_index(
            session, cluster_index, plan_repo=self._plans
        )
        progress.current_cluster_id = cluster_id
        progress.resume_pointer = ResumePointer(
            session_plan_id=plan_id,
            cluster_index=cluster_index,
            concept_index=concept_index,
            curriculum_cluster_id=cluster_id,
            current_concept=getattr(session, "current_concept", None),
        )

    async def handle_tutor_result(
        self,
        session: Session,
        result: dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        track_key = getattr(session, "progression_track_key", None)
        plan_id = getattr(session, "progression_session_plan_id", None)
        if not track_key or plan_id is None:
            return None

        progress = await self._progress.get_by_track(session.student_id, track_key)
        if progress is None:
            return None

        event_type = str(result.get("type") or "")
        if event_type not in ("teachback_passed", "completed"):
            await self._sync_resume_pointer(progress, session, plan_id)
            progress.updated_at = datetime.utcnow()
            await self._progress.save(progress)
            return await self.build_qa_payload(progress)

        prev_idx = max(0, int(getattr(session, "current_concept_index", 0) or 0) - 1)
        completed_ci = self._cluster_eval.completed_cluster_index_before_advance(
            session, previous_concept_index=prev_idx
        )
        cluster_id = await PlanSessionClusterRegistryExt.cluster_id_for_session_cluster_index(
            session, completed_ci, plan_repo=self._plans
        )
        if cluster_id is not None:
            self._session_engine.record_cluster_complete(
                progress,
                session_plan_id=plan_id,
                cluster_id=cluster_id,
            )

        plan = await self._plans.get_by_id(plan_id)
        if plan is None:
            await self._progress.save(progress)
            return await self.build_qa_payload(progress)

        completion = self._session_engine.evaluate(progress, plan)
        ordered = await self._unlock.list_ordered_plans(progress)
        self._session_engine.update_completion_percentage(progress, ordered_plans=ordered)

        transition: Optional[Dict[str, Any]] = None
        # Unlock the next planned session only when the runtime session finishes
        # (``completed``). ``teachback_passed`` advances concepts/clusters inside
        # the same runtime session and must not restart the next plan slice.
        if completion.is_complete and event_type == "completed":
            unlock = await self._unlock.on_session_completed(
                progress, completed_plan_id=plan_id
            )
            transition = {
                "session_complete": True,
                "unlock": {
                    "unlocked_plan_id": str(unlock.unlocked_plan_id)
                    if unlock.unlocked_plan_id
                    else None,
                    "auto_start_plan_id": str(unlock.auto_start_plan.id)
                    if unlock.auto_start_plan
                    else None,
                    "title": unlock.transition_title,
                    "subtitle": unlock.transition_subtitle,
                },
            }
            if unlock.auto_start_plan is not None:
                transition["auto_start"] = {
                    "catalog_session_plan_id": str(unlock.auto_start_plan.id)
                    if unlock.auto_start_plan.plan_scope == "catalog"
                    else None,
                    "sequence_number": unlock.auto_start_plan.sequence_number,
                }

        await self._sync_resume_pointer(progress, session, plan_id)
        progress.updated_at = datetime.utcnow()
        await self._progress.save(progress)

        payload = await self.build_qa_payload(progress)
        if transition:
            payload["transition"] = transition
        return payload

    async def build_qa_payload(
        self, progress: StudentPlanProgress
    ) -> Dict[str, Any]:
        ordered = await self._unlock.list_ordered_plans(progress)
        return {
            "learning_path": self._unlock.learning_path_snapshot(progress, ordered),
            "last_transition": progress.last_transition,
            "completion_percentage": progress.completion_percentage,
            "status": progress.status,
            "resume_pointer": progress.resume_pointer.model_dump(mode="json"),
        }

    async def get_progress_view(
        self, student_id: PydanticObjectId, track_key: str
    ) -> Optional[Dict[str, Any]]:
        progress = await self._progress.get_by_track(student_id, track_key)
        if progress is None:
            return None
        return await self.build_qa_payload(progress)
