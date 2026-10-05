"""Session and cluster introduction cards — pre-teaching pedagogical layer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan
from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.learning.sessions import Session
from app.repositories.class_session_plan_repository import ClassSessionPlanRepository
from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.repositories.curriculum_zone_repository import CurriculumZoneRepository
from app.services.curriculum.concept_pedagogy_aggregation import (
    aggregate_concept_pedagogy_bullets,
)
from app.services.progression.plan_session_cluster_registry_ext import (
    PlanSessionClusterRegistryExt,
)


def _has_intro_content(
    *,
    description: str,
    study_points: List[str],
    learning_outcomes: List[str],
) -> bool:
    return bool(
        (description or "").strip()
        or study_points
        or learning_outcomes
    )


def _build_narration(
    *,
    heading: str,
    title: str,
    description: str,
    study_points: List[str],
    learning_outcomes: List[str],
) -> str:
    """TTS-only narration — whiteboard uses structured pedagogy_card, not this prose."""
    parts: List[str] = []
    heading_clean = (heading or "").strip()
    title_clean = (title or "").strip()
    if heading_clean and title_clean:
        parts.append(f"{heading_clean}. {title_clean}.")
    elif title_clean:
        parts.append(f"{title_clean}.")
    desc = (description or "").strip()
    if desc:
        parts.append(desc)
    if study_points:
        parts.append("We will study:")
        for point in study_points:
            parts.append(f"{point}.")
    if learning_outcomes:
        parts.append("By the end you will be able to:")
        for outcome in learning_outcomes:
            parts.append(f"{outcome}.")
    return " ".join(parts)


class PedagogyIntroService:
    """Emit teacher-authored session/cluster intro cards before teaching."""

    def __init__(
        self,
        *,
        plan_repo: Optional[ClassSessionPlanRepository] = None,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
        zone_repo: Optional[CurriculumZoneRepository] = None,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._plans = plan_repo or ClassSessionPlanRepository()
        self._clusters = cluster_repo or CurriculumClusterRepository()
        self._zones = zone_repo or CurriculumZoneRepository()
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def maybe_emit(
        self,
        session: Session,
        *,
        action: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        flow = str(getattr(session, "flow_state", "idle") or "idle")

        # While an intro card is on screen, only the matching done action may advance.
        if flow == "pedagogy_session_intro":
            if action == "session_intro_done":
                session.pedagogy_session_intro_done = True
                session.flow_state = "idle"
                await session.save()
            else:
                return {"type": "noop"}

        elif flow == "pedagogy_cluster_intro":
            if action == "cluster_intro_done":
                cluster_idx = int(getattr(session, "current_cluster_index", 0) or 0)
                session.pedagogy_cluster_intro_done_for = cluster_idx
                session.flow_state = "idle"
                await session.save()
            else:
                return {"type": "noop"}

        if not bool(getattr(session, "pedagogy_session_intro_done", False)):
            payload = await self._session_intro_payload(session)
            if payload is not None:
                return self._build_response(payload, kind="session")
            session.pedagogy_session_intro_done = True
            await session.save()

        cluster_idx = int(getattr(session, "current_cluster_index", 0) or 0)
        done_raw = getattr(session, "pedagogy_cluster_intro_done_for", -1)
        done_for = -1 if done_raw is None else int(done_raw)
        if done_for < cluster_idx:
            if not bool(getattr(session, "pedagogy_session_recall_done", False)):
                if getattr(session, "progression_session_plan_id", None) is not None:
                    return None
            payload = await self._cluster_intro_payload(session, cluster_idx)
            if payload is not None:
                return self._build_response(payload, kind="cluster")
            session.pedagogy_cluster_intro_done_for = cluster_idx
            await session.save()

        return None

    async def _session_intro_payload(self, session: Session) -> Optional[Dict[str, Any]]:
        plan = await self._resolve_plan(session)
        if plan is None:
            return None
        # Teaching boundary is frozen on the Session at start (same keys/ids the
        # tutor uses). Aggregate concept pedagogy from that set — not plan-authored
        # session_study_points / session_learning_outcomes, and not whole clusters.
        concept_ids = list(getattr(session, "key_concept_ids", None) or [])
        concepts = await self._concepts.list_by_ids_ordered(concept_ids)
        study, outcomes = aggregate_concept_pedagogy_bullets(concepts)
        description = (plan.description or "").strip()
        if not _has_intro_content(
            description=description,
            study_points=study,
            learning_outcomes=outcomes,
        ):
            return None
        title = (plan.title or "").strip() or "Today's Session"
        seq = int(getattr(plan, "sequence_number", 1) or 1)
        return {
            "heading": f"SESSION {seq}",
            "title": title,
            "description": description,
            "study_points": study,
            "learning_outcomes": outcomes,
        }

    async def _cluster_intro_payload(
        self, session: Session, cluster_index: int
    ) -> Optional[Dict[str, Any]]:
        plan_id = getattr(session, "progression_session_plan_id", None)
        if plan_id is None:
            return None

        cluster = await self._resolve_cluster(session, cluster_index)
        if cluster is None:
            return None
        concepts = await self._concepts.list_by_cluster(
            cluster.id,
            organization_id=getattr(cluster, "organization_id", None),
        )
        study, outcomes = aggregate_concept_pedagogy_bullets(concepts)
        description = (getattr(cluster, "description", "") or "").strip()
        if not _has_intro_content(
            description=description,
            study_points=study,
            learning_outcomes=outcomes,
        ):
            return None
        title = (cluster.title or "").strip() or f"Cluster {cluster_index + 1}"
        return {
            "heading": "CLUSTER",
            "title": title,
            "description": description,
            "study_points": study,
            "learning_outcomes": outcomes,
        }

    async def _resolve_plan(self, session: Session) -> Optional[ClassSessionPlan]:
        plan_id = getattr(session, "progression_session_plan_id", None)
        if plan_id is None:
            return None
        return await self._plans.get_by_id(plan_id)

    async def _resolve_cluster(
        self, session: Session, cluster_index: int
    ) -> Optional[CurriculumCluster]:
        cluster_id = await PlanSessionClusterRegistryExt.cluster_id_for_session_cluster_index(
            session, cluster_index, plan_repo=self._plans
        )
        if cluster_id is not None:
            cluster = await self._clusters.get_by_id(cluster_id)
            if cluster is not None and cluster.deleted_at is None:
                return cluster

        return await self._cluster_by_manifest_index(session, cluster_index)

    async def _cluster_by_manifest_index(
        self, session: Session, cluster_index: int
    ) -> Optional[CurriculumCluster]:
        """Fallback for full-topic sessions without a plan id."""
        topic_id = session.topic_id
        clusters = await self._clusters.list_by_topic(
            topic_id,
            "teacher",
            organization_id=session.organization_id,
        )
        if not clusters:
            clusters = await self._clusters.list_by_topic(
                topic_id,
                "catalog",
                organization_id=None,
            )
        if not clusters:
            return None

        zones = await self._zones.list_by_topic(
            topic_id,
            clusters[0].topic_source,
            organization_id=session.organization_id,
        )
        zone_by_id = {z.id: z for z in zones}
        ordered: List[CurriculumCluster] = []
        by_zone: dict[int, List[CurriculumCluster]] = {}
        for cl in clusters:
            if cl.deleted_at is not None:
                continue
            zone = zone_by_id.get(cl.curriculum_zone_id)
            if zone is None or int(zone.zone_number) == 0:
                continue
            by_zone.setdefault(int(zone.zone_number), []).append(cl)
        for zn in sorted(by_zone.keys()):
            row = sorted(by_zone[zn], key=lambda c: c.sort_order)
            ordered.extend(row)
        if cluster_index < 0 or cluster_index >= len(ordered):
            return None
        return ordered[cluster_index]

    def _build_response(self, payload: Dict[str, Any], *, kind: str) -> Dict[str, Any]:
        card = {
            "kind": kind,
            "heading": payload["heading"],
            "title": payload["title"],
            "description": payload.get("description") or "",
            "study_points": payload.get("study_points") or [],
            "learning_outcomes": payload.get("learning_outcomes") or [],
        }
        narration = _build_narration(
            heading=card["heading"],
            title=card["title"],
            description=card["description"],
            study_points=card["study_points"],
            learning_outcomes=card["learning_outcomes"],
        )
        response_type = (
            "session_intro_card" if kind == "session" else "cluster_intro_card"
        )
        flow_state = (
            "pedagogy_session_intro" if kind == "session" else "pedagogy_cluster_intro"
        )
        return {
            "type": response_type,
            "message": narration,
            "pedagogy_card": card,
            "visual": {"type": "pedagogy_intro", "card": card},
            "flow_state": flow_state,
        }

    async def apply_flow_state(self, session: Session, result: Dict[str, Any]) -> None:
        fs = result.get("flow_state")
        if fs:
            session.flow_state = str(fs)
            await session.save()
