"""RAG loads notes by structured concept_id first."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.rag_service import RAGService


@pytest.mark.asyncio
async def test_get_topic_notes_prefers_concept_id():
    concept_id = PydanticObjectId()
    note = SimpleNamespace(
        id=PydanticObjectId(),
        concept_id=concept_id,
        concept="non-living things",
        content_markdown="- Rocks do not grow.",
        note_type="detailed",
        approved=True,
        organization_id=None,
        source_type="teacher",
        usage_count=0,
        updated_at=None,
        teaching_style=None,
        interest_category=None,
        difficulty_level="medium",
        embedding=None,
        update=AsyncMock(),
    )
    repo = MagicMock()
    repo.get_notes_by_concept_id = AsyncMock(return_value=[note])
    repo.get_notes = AsyncMock(return_value=[])
    rag = RAGService(repo, MagicMock(), MagicMock(), MagicMock())

    async def _no_extra(*_a, **_k):
        return []

    rag._extra_teacher_topic_storage_ids = _no_extra  # type: ignore[method-assign]

    topic_id = PydanticObjectId()
    org_id = PydanticObjectId()
    out = await rag.get_topic_notes(
        topic_id=topic_id,
        organization_id=org_id,
        current_concept="what are non living things?",
        concept_id=concept_id,
        vtse_authoring=True,
    )

    assert out == [note]
    repo.get_notes_by_concept_id.assert_awaited()
    repo.get_notes.assert_not_awaited()
