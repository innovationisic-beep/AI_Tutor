"""Tests for session concept id tracking."""

from __future__ import annotations

from types import SimpleNamespace

from beanie.odm.fields import PydanticObjectId

from app.services.session_concept_tracking import (
    session_concept_id_for_rag,
    sync_session_concept_fields,
)


def test_sync_session_concept_fields_pairs_string_and_id():
    id0 = PydanticObjectId()
    id1 = PydanticObjectId()
    session = SimpleNamespace(
        current_concept_index=0,
        key_concepts=["living things", "non-living things"],
        key_concept_ids=[id0, id1],
        current_concept=None,
        current_concept_id=None,
    )
    sync_session_concept_fields(session, index=1)
    assert session.current_concept == "non-living things"
    assert session.current_concept_id == id1


def test_session_concept_id_for_rag_prefers_explicit_current():
    cid = PydanticObjectId()
    session = SimpleNamespace(
        current_concept_id=cid,
        current_concept_index=0,
        key_concept_ids=[PydanticObjectId()],
    )
    assert session_concept_id_for_rag(session) == cid
