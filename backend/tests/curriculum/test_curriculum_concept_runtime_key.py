"""Runtime key updates on curriculum concepts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.curriculum.curriculum_concept_service import CurriculumConceptService


@pytest.mark.asyncio
async def test_update_canonical_runtime_key_syncs_linked_notes():
    concept_id = PydanticObjectId()
    topic_id = PydanticObjectId()
    concept = SimpleNamespace(
        id=concept_id,
        topic_id=topic_id,
        topic_source="catalog",
        display_name="Non-living things",
        canonical_runtime_key="what are non living things?",
        sort_order=0,
        difficulty_level="basic",
        estimated_learning_minutes=10,
        status="draft",
        deleted_at=None,
        organization_id=None,
        save=AsyncMock(),
    )
    ctx = SimpleNamespace(
        topic_id=topic_id,
        topic_source="catalog",
        organization_id=None,
    )
    note = SimpleNamespace(
        concept="what are non living things?",
        concept_source="structured",
        save=AsyncMock(),
    )

    svc = CurriculumConceptService()
    svc.get = AsyncMock(return_value=concept)  # type: ignore[method-assign]
    svc._concepts.canonical_runtime_key_exists = AsyncMock(return_value=False)  # type: ignore[attr-defined]

    with patch(
        "app.services.curriculum.curriculum_concept_service.TopicNote.find",
        return_value=MagicMock(to_list=AsyncMock(return_value=[note])),
    ), patch(
        "app.services.curriculum.curriculum_concept_service.TopicQuestionBank.find",
        return_value=MagicMock(to_list=AsyncMock(return_value=[])),
    ):
        updated = await svc.update(
            concept_id,
            ctx,  # type: ignore[arg-type]
            canonical_runtime_key="Non-living things",
        )

    assert updated.canonical_runtime_key == "non-living things"
    assert note.concept == "non-living things"
    note.save.assert_awaited_once()
    concept.save.assert_awaited_once()
