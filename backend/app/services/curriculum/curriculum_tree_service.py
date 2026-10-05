from __future__ import annotations

from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.repositories.curriculum_cluster_repository import (
    CurriculumClusterRepository,
    get_curriculum_cluster_repository,
)
from app.repositories.curriculum_concept_repository import (
    CurriculumConceptRepository,
    get_curriculum_concept_repository,
)
from app.repositories.curriculum_zone_repository import (
    CurriculumZoneRepository,
    get_curriculum_zone_repository,
)
from app.services.curriculum.curriculum_validators import allows_vtse_for_zone
from app.services.curriculum.topic_context_service import TopicContext


def _zone_dict(zone: Any, clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(zone.id),
        "zone_number": zone.zone_number,
        "title": zone.title,
        "description": zone.description,
        "purpose": zone.purpose,
        "allows_vtse": allows_vtse_for_zone(int(zone.zone_number)),
        "is_system_zone": zone.is_system_zone,
        "sort_order": zone.sort_order,
        "status": zone.status,
        "clusters": clusters,
    }


def _cluster_dict(cluster: Any, concepts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": str(cluster.id),
        "curriculum_zone_id": str(cluster.curriculum_zone_id),
        "cluster_number": cluster.cluster_number,
        "title": cluster.title,
        "description": getattr(cluster, "description", "") or "",
        "study_points": list(getattr(cluster, "study_points", None) or []),
        "learning_outcomes": list(getattr(cluster, "learning_outcomes", None) or []),
        "sort_order": cluster.sort_order,
        "estimated_learning_minutes": cluster.estimated_learning_minutes,
        "status": cluster.status,
        "concepts": concepts,
    }


def _concept_dict(concept: Any) -> Dict[str, Any]:
    from app.services.curriculum.concept_teaching_sequence import normalize_story_hook
    from app.services.curriculum.concept_vtse_template import (
        normalize_vtse_template,
        vtse_template_to_dict,
    )
    from app.services.visual_teaching.authored import normalize_visual_teaching

    hook = normalize_story_hook(getattr(concept, "story_hook", None))
    vt_pkg = normalize_visual_teaching(getattr(concept, "visual_teaching", None))
    vtse = None
    try:
        vtse = vtse_template_to_dict(normalize_vtse_template(getattr(concept, "vtse_template", None)))
    except Exception:  # noqa: BLE001
        raw = getattr(concept, "vtse_template", None)
        vtse = dict(raw) if isinstance(raw, dict) else None
    return {
        "id": str(concept.id),
        "curriculum_zone_id": str(concept.curriculum_zone_id),
        "curriculum_cluster_id": str(concept.curriculum_cluster_id),
        "slug": concept.slug,
        "display_name": concept.display_name,
        "canonical_runtime_key": concept.canonical_runtime_key,
        "sort_order": concept.sort_order,
        "difficulty_level": concept.difficulty_level,
        "estimated_learning_minutes": concept.estimated_learning_minutes,
        "study_points": list(getattr(concept, "study_points", None) or []),
        "learning_outcomes": list(getattr(concept, "learning_outcomes", None) or []),
        "story_hook": hook.model_dump() if hook else None,
        "visual_teaching": vt_pkg.model_dump() if vt_pkg else None,
        "teaching_sequence": list(getattr(concept, "teaching_sequence", None) or []),
        "teaching_sequence_mode": str(
            getattr(concept, "teaching_sequence_mode", None) or "manual"
        ),
        "teaching_sequence_auto_status": str(
            getattr(concept, "teaching_sequence_auto_status", None) or ""
        ),
        "vtse_template": vtse,
        "vtse_visuals": getattr(concept, "vtse_visuals", None),
        "status": concept.status,
        "published_revision": concept.published_revision,
    }


class CurriculumTreeService:
    def __init__(
        self,
        zone_repo: Optional[CurriculumZoneRepository] = None,
        cluster_repo: Optional[CurriculumClusterRepository] = None,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._zones = zone_repo or get_curriculum_zone_repository()
        self._clusters = cluster_repo or get_curriculum_cluster_repository()
        self._concepts = concept_repo or get_curriculum_concept_repository()

    async def get_tree(self, ctx: TopicContext) -> Dict[str, Any]:
        zones = await self._zones.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
        )
        zone_ids = [z.id for z in zones]
        clusters = await self._clusters.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            zone_ids=zone_ids if zone_ids else [],
        )
        cluster_ids = [c.id for c in clusters]
        concepts = await self._concepts.list_by_topic(
            ctx.topic_id,
            ctx.topic_source,
            organization_id=ctx.organization_id,
            cluster_ids=cluster_ids if cluster_ids else [],
        )

        concepts_by_cluster: Dict[str, List[Dict[str, Any]]] = {}
        for c in concepts:
            key = str(c.curriculum_cluster_id)
            concepts_by_cluster.setdefault(key, []).append(_concept_dict(c))
        for key in concepts_by_cluster:
            concepts_by_cluster[key].sort(key=lambda x: x["sort_order"])

        clusters_by_zone: Dict[str, List[Dict[str, Any]]] = {}
        for cl in clusters:
            zkey = str(cl.curriculum_zone_id)
            cl_concepts = concepts_by_cluster.get(str(cl.id), [])
            clusters_by_zone.setdefault(zkey, []).append(
                _cluster_dict(cl, cl_concepts)
            )
        for key in clusters_by_zone:
            clusters_by_zone[key].sort(key=lambda x: x["sort_order"])

        zone_out = []
        for z in zones:
            z_clusters = clusters_by_zone.get(str(z.id), [])
            zone_out.append(_zone_dict(z, z_clusters))

        return {
            "topic_id": str(ctx.topic_id),
            "topic_source": ctx.topic_source,
            "topic_name": ctx.topic_name,
            "curriculum_schema_version": ctx.curriculum_schema_version,
            "curriculum_revision": ctx.curriculum_revision,
            "curriculum_published_at": (
                ctx.curriculum_published_at.isoformat()
                if ctx.curriculum_published_at
                else None
            ),
            "supports_class_sessions": ctx.supports_class_sessions,
            "zones": zone_out,
        }
