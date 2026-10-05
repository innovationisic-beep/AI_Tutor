from __future__ import annotations

from dataclasses import dataclass
from typing import List

from beanie.odm.fields import PydanticObjectId

from app.models.classroom.class_session_plan import ClassSessionPlan, ClassSessionPlanItem


@dataclass(frozen=True)
class AssignedCluster:
    curriculum_cluster_id: PydanticObjectId
    cluster_index: int
    zone_number: int
    runtime_keys: List[str]
    display_name: str


class PlanSessionClusterRegistry:
    """Maps a session plan to the clusters assigned for completion."""

    @staticmethod
    def assigned_clusters(plan: ClassSessionPlan) -> List[AssignedCluster]:
        items = sorted(plan.items, key=lambda row: row.sort_order)
        by_cluster: dict[PydanticObjectId, AssignedCluster] = {}
        cluster_index = 0

        for item in items:
            if item.item_type == "zone_coverage" or item.item_type == "non_curriculum":
                continue
            if item.curriculum_cluster_id is None:
                continue
            cid = item.curriculum_cluster_id
            keys = list(item.resolved_runtime_keys or [])
            if item.canonical_runtime_key_snapshot and item.item_type == "concept_coverage":
                k = item.canonical_runtime_key_snapshot.strip()
                if k and k not in keys:
                    keys.append(k)

            existing = by_cluster.get(cid)
            if existing is None:
                by_cluster[cid] = AssignedCluster(
                    curriculum_cluster_id=cid,
                    cluster_index=cluster_index,
                    zone_number=int(item.zone_number or 1),
                    runtime_keys=keys,
                    display_name=(item.display_name_snapshot or "Cluster").strip(),
                )
                cluster_index += 1
            else:
                merged = list(existing.runtime_keys)
                for k in keys:
                    if k not in merged:
                        merged.append(k)
                by_cluster[cid] = AssignedCluster(
                    curriculum_cluster_id=cid,
                    cluster_index=existing.cluster_index,
                    zone_number=existing.zone_number,
                    runtime_keys=merged,
                    display_name=existing.display_name,
                )

        return sorted(by_cluster.values(), key=lambda row: row.cluster_index)

    @staticmethod
    def first_zone_number(plan: ClassSessionPlan) -> int:
        """Lowest curriculum zone referenced by clusters in this session plan."""
        assigned = PlanSessionClusterRegistry.assigned_clusters(plan)
        if not assigned:
            return 1
        return min(int(row.zone_number) for row in assigned)

    @staticmethod
    def cluster_id_for_index(
        plan: ClassSessionPlan, cluster_index: int
    ) -> PydanticObjectId | None:
        for row in PlanSessionClusterRegistry.assigned_clusters(plan):
            if row.cluster_index == cluster_index:
                return row.curriculum_cluster_id
        return None
