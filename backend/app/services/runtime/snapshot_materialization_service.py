"""Freeze cluster concept keys into plan snapshot items at instance creation."""

from __future__ import annotations

from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.classroom.class_session_plan import ClassSessionPlanItem
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.curriculum_validators import normalize_runtime_key


class SnapshotMaterializationService:
    def __init__(
        self,
        concept_repo: CurriculumConceptRepository | None = None,
    ) -> None:
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def materialize_items(
        self,
        items: List[ClassSessionPlanItem],
        *,
        organization_id: Optional[PydanticObjectId] = None,
    ) -> List[ClassSessionPlanItem]:
        """One-time tree read when scheduling; student launch reads snapshot only."""
        out: List[ClassSessionPlanItem] = []
        for item in items:
            if item.item_type in ("non_curriculum", "zone_coverage"):
                out.append(item.model_copy(deep=True))
                continue

            if item.item_type == "cluster_coverage":
                if item.curriculum_cluster_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="cluster_coverage requires curriculum_cluster_id",
                    )
                concepts = await self._concepts.list_by_cluster(
                    item.curriculum_cluster_id,
                    organization_id=organization_id,
                )
                if not concepts:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="SNAPSHOT_NOT_MATERIALIZED: cluster has no concepts",
                    )
                keys = [
                    normalize_runtime_key(c.canonical_runtime_key) for c in concepts
                ]
                ids = [c.id for c in concepts]
                out.append(
                    item.model_copy(
                        update={
                            "resolved_runtime_keys": keys,
                            "resolved_concept_ids": ids,
                        },
                        deep=True,
                    )
                )
                continue

            if item.item_type == "concept_coverage":
                key = item.canonical_runtime_key_snapshot
                if not key or not str(key).strip():
                    if item.curriculum_concept_id is None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="concept_coverage requires curriculum_concept_id",
                        )
                    concept = await self._concepts.get_by_id(item.curriculum_concept_id)
                    if concept is None or concept.deleted_at is not None:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid curriculum_concept_id",
                        )
                    key = concept.canonical_runtime_key
                normalized = normalize_runtime_key(str(key))
                cid = item.curriculum_concept_id
                if cid is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="concept_coverage requires curriculum_concept_id",
                    )
                out.append(
                    item.model_copy(
                        update={
                            "canonical_runtime_key_snapshot": normalized,
                            "resolved_runtime_keys": [normalized],
                            "resolved_concept_ids": [cid],
                        },
                        deep=True,
                    )
                )
                continue

            out.append(item.model_copy(deep=True))
        return out
