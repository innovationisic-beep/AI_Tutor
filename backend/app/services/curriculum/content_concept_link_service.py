"""Resolve dual-link concept identity for content authoring (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.content.topic_notes import TopicNote
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_enums import TopicSource
from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.curriculum_validators import normalize_runtime_key

ConceptSourceType = Literal["legacy", "structured"]


@dataclass(frozen=True)
class ResolvedConceptLink:
    concept_id: Optional[PydanticObjectId]
    concept: Optional[str]
    concept_source: Optional[ConceptSourceType]


class ContentConceptLinkService:
    def __init__(
        self,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def resolve_for_authoring(
        self,
        *,
        curriculum_schema_version: str,
        topic_id: PydanticObjectId,
        topic_source: TopicSource,
        organization_id: Optional[PydanticObjectId],
        concept_id: Optional[str],
        concept: Optional[str],
        is_structured_flow: bool = False,
        topic: Optional[Topic] = None,
        teacher_topic: Optional[TeacherTopic] = None,
    ) -> ResolvedConceptLink:
        schema = (curriculum_schema_version or "v1").strip().lower()
        has_concept_id = bool(concept_id and str(concept_id).strip())

        if schema == "v1" and has_concept_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="concept_id is not allowed for v1 topics",
            )

        if is_structured_flow:
            return await self._resolve_structured(
                topic_id=topic_id,
                topic_source=topic_source,
                organization_id=organization_id,
                concept_id=concept_id,
                concept=concept,
                schema=schema,
            )

        if has_concept_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="concept_id is only allowed in structured authoring flows",
            )

        return self._resolve_legacy_string(
            concept=concept,
            topic=topic,
            teacher_topic=teacher_topic,
        )

    async def _resolve_structured(
        self,
        *,
        topic_id: PydanticObjectId,
        topic_source: TopicSource,
        organization_id: Optional[PydanticObjectId],
        concept_id: Optional[str],
        concept: Optional[str],
        schema: str,
    ) -> ResolvedConceptLink:
        if schema != "v2":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="structured authoring requires curriculum_schema_version v2",
            )

        if not concept_id or not str(concept_id).strip():
            if concept is None or not str(concept).strip():
                return ResolvedConceptLink(None, None, None)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="concept_id is required for structured concept-scoped content",
            )

        cc = await self._load_concept_for_topic(
            concept_id=str(concept_id).strip(),
            topic_id=topic_id,
            topic_source=topic_source,
            organization_id=organization_id,
        )
        runtime = normalize_runtime_key(cc.canonical_runtime_key)
        if concept is not None and str(concept).strip():
            supplied = normalize_runtime_key(str(concept))
            if supplied != runtime:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="concept string does not match canonical_runtime_key",
                )
        return ResolvedConceptLink(cc.id, runtime, "structured")

    def _resolve_legacy_string(
        self,
        *,
        concept: Optional[str],
        topic: Optional[Topic],
        teacher_topic: Optional[TeacherTopic],
    ) -> ResolvedConceptLink:
        if teacher_topic is not None:
            try:
                normalized = TopicNote.validate_concept_for_teacher_topic(
                    teacher_topic, concept
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
        elif topic is not None:
            try:
                normalized = TopicNote.validate_concept_for_topic(topic, concept)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
        else:
            if concept is None or not str(concept).strip():
                normalized = None
            else:
                normalized = normalize_runtime_key(str(concept))

        if normalized is None:
            return ResolvedConceptLink(None, None, None)
        return ResolvedConceptLink(None, normalized, "legacy")

    async def _load_concept_for_topic(
        self,
        *,
        concept_id: str,
        topic_id: PydanticObjectId,
        topic_source: TopicSource,
        organization_id: Optional[PydanticObjectId],
    ) -> CurriculumConcept:
        try:
            cid = PydanticObjectId(concept_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid concept_id"
            ) from exc

        concept = await self._concepts.get_by_id(cid)
        if concept is None or concept.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Curriculum concept not found",
            )
        if concept.topic_id != topic_id or concept.topic_source != topic_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="concept does not belong to this topic",
            )
        if organization_id is not None and concept.organization_id not in (
            None,
            organization_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Curriculum concept not in your organization",
            )
        if concept.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot link content to an archived concept",
            )
        return concept

    @staticmethod
    def derive_runtime_string(concept: CurriculumConcept) -> str:
        return normalize_runtime_key(concept.canonical_runtime_key)
