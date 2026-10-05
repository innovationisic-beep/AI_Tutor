"""Unit tests for ContentConceptLinkService (Phase 2)."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic
from app.services.curriculum.content_concept_link_service import (
    ContentConceptLinkService,
)


@pytest.mark.asyncio
async def test_v1_rejects_concept_id():
    svc = ContentConceptLinkService()
    with pytest.raises(HTTPException) as exc:
        await svc.resolve_for_authoring(
            curriculum_schema_version="v1",
            topic_id=PydanticObjectId(),
            topic_source="catalog",
            organization_id=None,
            concept_id="674a1b2c3d4e5f6789012345",
            concept="photosynthesis",
        )
    assert exc.value.status_code == 400
    assert "v1" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_v1_legacy_string_concept(db, catalog_topic):
    svc = ContentConceptLinkService()
    topic = await Topic.get(catalog_topic.id)
    assert topic is not None
    topic.key_concepts = ["light reaction"]
    await topic.save()
    link = await svc.resolve_for_authoring(
        curriculum_schema_version="v1",
        topic_id=topic.id,
        topic_source="catalog",
        organization_id=None,
        concept_id=None,
        concept="Light Reaction",
        topic=topic,
    )
    assert link.concept_id is None
    assert link.concept == "light reaction"
    assert link.concept_source == "legacy"


@pytest.mark.asyncio
async def test_v2_structured_derives_concept_string(db, catalog_topic):
    svc = ContentConceptLinkService()
    concept = CurriculumConcept(
        organization_id=None,
        topic_id=catalog_topic.id,
        topic_source="catalog",
        curriculum_zone_id=PydanticObjectId(),
        curriculum_cluster_id=PydanticObjectId(),
        slug="concept-a",
        display_name="Concept A",
        canonical_runtime_key="concept-a",
        status="draft",
    )
    await concept.insert()

    link = await svc.resolve_for_authoring(
        curriculum_schema_version="v2",
        topic_id=catalog_topic.id,
        topic_source="catalog",
        organization_id=None,
        concept_id=str(concept.id),
        concept=None,
        is_structured_flow=True,
    )
    assert link.concept_id == concept.id
    assert link.concept == "concept-a"
    assert link.concept_source == "structured"


@pytest.mark.asyncio
async def test_v2_legacy_flow_rejects_concept_id(db, teacher_topic):
    svc = ContentConceptLinkService()
    tt = await TeacherTopic.get(teacher_topic.id)
    assert tt is not None
    tt.curriculum_schema_version = "v2"
    with pytest.raises(HTTPException) as exc:
        await svc.resolve_for_authoring(
            curriculum_schema_version="v2",
            topic_id=tt.id,
            topic_source="teacher",
            organization_id=tt.organization_id,
            concept_id="674a1b2c3d4e5f6789012345",
            concept="light reaction",
            is_structured_flow=False,
            teacher_topic=tt,
        )
    assert exc.value.status_code == 400
