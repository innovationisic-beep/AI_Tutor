"""Tests for pedagogy introduction cards."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.pedagogy.pedagogy_intro_service import (
    PedagogyIntroService,
    _build_narration,
    _has_intro_content,
)


def test_has_intro_content_requires_bullets_or_description():
    assert not _has_intro_content(description="", study_points=[], learning_outcomes=[])
    assert _has_intro_content(description="Overview", study_points=[], learning_outcomes=[])
    assert _has_intro_content(description="", study_points=["A"], learning_outcomes=[])


def test_build_narration_includes_sections():
    text = _build_narration(
        heading="SESSION 1",
        title="Photosynthesis",
        description="We explore plants.",
        study_points=["Light reactions", "Calvin cycle"],
        learning_outcomes=["Explain chlorophyll role"],
    )
    assert "SESSION 1" in text
    assert "Photosynthesis" in text
    assert "Light reactions" in text
    assert "chlorophyll" in text


def test_build_narration_section_intros_once_per_list():
    text = _build_narration(
        heading="CLUSTER",
        title="Living things",
        description="",
        study_points=["Growth", "Reproduction"],
        learning_outcomes=["Name three traits", "Compare living and non-living"],
    )
    assert text.count("We will study:") == 1
    assert text.count("By the end you will be able to:") == 1
    assert "Growth." in text
    assert "Reproduction." in text
    assert "Name three traits." in text


def _session_stub(**kwargs):
    defaults = dict(
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        mode="explorer",
        ai_model_used="test",
        start_time=datetime.utcnow(),
        flow_state="idle",
        pedagogy_session_intro_done=False,
        pedagogy_cluster_intro_done_for=-1,
        current_cluster_index=0,
        progression_session_plan_id=None,
        key_concept_ids=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_maybe_emit_skips_when_no_plan():
    session = _session_stub()
    session.save = AsyncMock()
    svc = PedagogyIntroService()
    result = await svc.maybe_emit(session, action=None)
    assert result is None
    assert session.pedagogy_session_intro_done is True


@pytest.mark.asyncio
async def test_maybe_emit_session_intro_card():
    plan_id = PydanticObjectId()
    c1 = PydanticObjectId()
    c2 = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        title="Session One",
        description="Intro overview",
        sequence_number=1,
        # Plan-authored bullets must NOT appear on the Session Card.
        session_study_points=["Stale plan study"],
        session_learning_outcomes=["Stale plan outcome"],
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    class FakeConceptRepo:
        async def list_by_ids_ordered(self, concept_ids):
            assert concept_ids == [c1, c2]
            return [
                SimpleNamespace(
                    id=c1,
                    sort_order=0,
                    study_points=["Concept study 1", "Shared"],
                    learning_outcomes=["Concept outcome 1"],
                ),
                SimpleNamespace(
                    id=c2,
                    sort_order=0,
                    study_points=["Shared", "Concept study 2"],
                    learning_outcomes=["Concept outcome 2"],
                ),
            ]

        async def list_by_cluster(self, *args, **kwargs):
            raise AssertionError("session intro must not list_by_cluster")

    session = _session_stub(
        progression_session_plan_id=plan_id,
        key_concept_ids=[c1, c2],
    )
    session.pedagogy_session_recall_done = True
    session.save = AsyncMock()

    svc = PedagogyIntroService(
        plan_repo=FakePlanRepo(),
        concept_repo=FakeConceptRepo(),
    )
    first = await svc.maybe_emit(session, action=None)
    assert first is not None
    assert first["type"] == "session_intro_card"
    assert first["pedagogy_card"]["title"] == "Session One"
    assert first["pedagogy_card"]["heading"] == "SESSION 1"
    assert first["pedagogy_card"]["description"] == "Intro overview"
    assert first["pedagogy_card"]["study_points"] == [
        "Concept study 1",
        "Shared",
        "Concept study 2",
    ]
    assert first["pedagogy_card"]["learning_outcomes"] == [
        "Concept outcome 1",
        "Concept outcome 2",
    ]
    assert "Stale plan study" not in first["pedagogy_card"]["study_points"]
    assert "Stale plan outcome" not in first["pedagogy_card"]["learning_outcomes"]


@pytest.mark.asyncio
async def test_session_intro_respects_key_concept_id_subset_order():
    """concept_coverage subset: only session key_concept_ids, in teaching order."""
    plan_id = PydanticObjectId()
    taught = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        title="Subset Session",
        description="",
        sequence_number=1,
        session_study_points=[],
        session_learning_outcomes=[],
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    class FakeConceptRepo:
        async def list_by_ids_ordered(self, concept_ids):
            assert concept_ids == [taught]
            return [
                SimpleNamespace(
                    id=taught,
                    sort_order=99,
                    study_points=["Only taught concept"],
                    learning_outcomes=["Only taught outcome"],
                )
            ]

    session = _session_stub(
        progression_session_plan_id=plan_id,
        key_concept_ids=[taught],
        pedagogy_session_recall_done=True,
    )
    session.save = AsyncMock()

    svc = PedagogyIntroService(
        plan_repo=FakePlanRepo(),
        concept_repo=FakeConceptRepo(),
    )
    svc._cluster_intro_payload = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await svc.maybe_emit(session, action=None)
    assert result is not None
    assert result["type"] == "session_intro_card"
    assert result["pedagogy_card"]["study_points"] == ["Only taught concept"]
    assert result["pedagogy_card"]["learning_outcomes"] == ["Only taught outcome"]


@pytest.mark.asyncio
async def test_maybe_emit_waits_for_session_intro_done():
    plan_id = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        title="Session One",
        description="Intro",
        sequence_number=2,
        session_study_points=["A"],
        session_learning_outcomes=["B"],
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    session = _session_stub(
        progression_session_plan_id=plan_id,
        flow_state="pedagogy_session_intro",
        pedagogy_session_recall_done=True,
    )
    session.save = AsyncMock()

    svc = PedagogyIntroService(plan_repo=FakePlanRepo())
    svc._cluster_intro_payload = AsyncMock(return_value=None)  # type: ignore[method-assign]
    noop = await svc.maybe_emit(session, action=None)
    assert noop == {"type": "noop"}

    done = await svc.maybe_emit(session, action="session_intro_done")
    assert done is None
    assert session.pedagogy_session_intro_done is True


@pytest.mark.asyncio
async def test_maybe_emit_cluster_intro_once_per_cluster():
    plan_id = PydanticObjectId()
    cluster_id = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        title="Session One",
        description="",
        sequence_number=1,
        session_study_points=[],
        session_learning_outcomes=[],
    )
    cluster = SimpleNamespace(
        id=cluster_id,
        title="Cluster Alpha",
        description="Cluster overview",
        study_points=["Legacy cluster point ignored"],
        learning_outcomes=["Legacy cluster outcome ignored"],
        deleted_at=None,
        curriculum_zone_id=PydanticObjectId(),
        sort_order=0,
        topic_source="catalog",
    )
    concept_rows = [
        SimpleNamespace(
            id=PydanticObjectId(),
            sort_order=0,
            study_points=["Point 1"],
            learning_outcomes=["Outcome 1"],
        ),
        SimpleNamespace(
            id=PydanticObjectId(),
            sort_order=1,
            study_points=["Point 1", "Point 2"],
            learning_outcomes=["Outcome 2"],
        ),
    ]

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    class FakeClusterRepo:
        async def get_by_id(self, cid):
            return cluster if cid == cluster_id else None

    class FakeConceptRepo:
        async def list_by_cluster(self, cid, *, organization_id=None):
            assert cid == cluster_id
            return concept_rows

    session = _session_stub(
        progression_session_plan_id=plan_id,
        pedagogy_session_intro_done=True,
        pedagogy_session_recall_done=True,
        flow_state="idle",
    )
    session.save = AsyncMock()

    svc = PedagogyIntroService(
        plan_repo=FakePlanRepo(),
        cluster_repo=FakeClusterRepo(),
        concept_repo=FakeConceptRepo(),
    )
    svc._resolve_cluster = AsyncMock(return_value=cluster)  # type: ignore[method-assign]

    first = await svc.maybe_emit(session, action=None)
    assert first is not None
    assert first["type"] == "cluster_intro_card"
    assert first["pedagogy_card"]["heading"] == "CLUSTER"
    assert first["pedagogy_card"]["study_points"] == ["Point 1", "Point 2"]
    assert first["pedagogy_card"]["learning_outcomes"] == ["Outcome 1", "Outcome 2"]
    session.flow_state = str(first["flow_state"])

    noop = await svc.maybe_emit(session, action=None)
    assert noop == {"type": "noop"}

    done = await svc.maybe_emit(session, action="cluster_intro_done")
    assert done is None
    assert session.pedagogy_cluster_intro_done_for == 0

    again = await svc.maybe_emit(session, action=None)
    assert again is None


@pytest.mark.asyncio
async def test_cluster_intro_skips_when_concepts_have_no_bullets_and_no_description():
    plan_id = PydanticObjectId()
    cluster_id = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        title="Session One",
        description="",
        sequence_number=1,
        session_study_points=[],
        session_learning_outcomes=[],
    )
    cluster = SimpleNamespace(
        id=cluster_id,
        title="Empty Cluster",
        description="",
        deleted_at=None,
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    class FakeConceptRepo:
        async def list_by_cluster(self, cid, *, organization_id=None):
            return [
                SimpleNamespace(
                    id=PydanticObjectId(),
                    sort_order=0,
                    study_points=[],
                    learning_outcomes=[],
                )
            ]

    session = _session_stub(
        progression_session_plan_id=plan_id,
        pedagogy_session_intro_done=True,
        pedagogy_session_recall_done=True,
        flow_state="idle",
    )
    session.save = AsyncMock()

    svc = PedagogyIntroService(
        plan_repo=FakePlanRepo(),
        concept_repo=FakeConceptRepo(),
    )
    svc._resolve_cluster = AsyncMock(return_value=cluster)  # type: ignore[method-assign]
    result = await svc.maybe_emit(session, action=None)
    assert result is None
    assert session.pedagogy_cluster_intro_done_for == 0
