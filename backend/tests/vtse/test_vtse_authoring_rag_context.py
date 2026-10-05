"""VTSE authoring must use concept-scoped RAG only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.handlers.zone1_timeline_finalize import (
    cluster_context_snapshot_for_cir,
    resolve_vtse_concept_identity,
)


def test_cluster_context_snapshot_uses_current_cluster_only():
    session = SimpleNamespace(
        current_cluster_index=1,
        concept_clusters=[
            ["living things", "grow"],
            ["non-living things"],
        ],
    )
    assert cluster_context_snapshot_for_cir(session) == "non-living things"


def test_cluster_context_snapshot_empty_when_out_of_range():
    session = SimpleNamespace(current_cluster_index=5, concept_clusters=[["a"]])
    assert cluster_context_snapshot_for_cir(session) == ""


@pytest.mark.asyncio
async def test_resolve_vtse_concept_identity_question_runtime_key():
    identity = await resolve_vtse_concept_identity(
        session=SimpleNamespace(topic_id=None, organization_id=None, current_concept=None),
        concept="what are non living things?",
    )
    assert identity.anchor_label == "Non living things"
    assert "what are non living things?" in identity.rag_lookup_keys


@pytest.mark.asyncio
async def test_resolve_vtse_concept_identity_display_name_preserved():
    identity = await resolve_vtse_concept_identity(
        session=SimpleNamespace(topic_id=None, organization_id=None, current_concept=None),
        concept="non-living things",
    )
    assert identity.anchor_label == "non-living things"
