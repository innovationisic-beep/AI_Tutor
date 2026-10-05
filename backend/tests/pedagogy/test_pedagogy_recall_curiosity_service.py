"""Tests for session recall and cluster curiosity layers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.pedagogy.pedagogy_recall_curiosity_service import (
    PedagogyRecallCuriosityService,
    session_recall_blocks_cluster_intro,
    session_recall_required,
)


def _session_stub(**kwargs):
    defaults = dict(
        organization_id=PydanticObjectId(),
        student_id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        mode="explorer",
        ai_model_used="test",
        start_time=datetime.utcnow(),
        flow_state="idle",
        pedagogy_session_intro_done=True,
        pedagogy_session_recall_done=False,
        pedagogy_cluster_intro_done_for=-1,
        pedagogy_cluster_curiosity_done_for=-1,
        current_cluster_index=0,
        progression_session_plan_id=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_session_recall_skipped_for_session_one():
    plan_id = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        sequence_number=1,
        catalog_topic_id=PydanticObjectId(),
        plan_scope="catalog",
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    session = _session_stub(progression_session_plan_id=plan_id)
    session.save = AsyncMock()
    svc = PedagogyRecallCuriosityService(plan_repo=FakePlanRepo())
    result = await svc.maybe_emit(session, action=None)
    assert result is None
    assert session.pedagogy_session_recall_done is True


@pytest.mark.asyncio
async def test_session_recall_blocks_cluster_intro_via_flag():
    session = _session_stub(
        progression_session_plan_id=PydanticObjectId(),
        pedagogy_session_recall_done=False,
    )
    assert await session_recall_blocks_cluster_intro(session) is True
    session.pedagogy_session_recall_done = True
    assert await session_recall_blocks_cluster_intro(session) is False


@pytest.mark.asyncio
async def test_cluster_curiosity_after_cluster_intro():
    plan_id = PydanticObjectId()
    plan = SimpleNamespace(
        id=plan_id,
        sequence_number=1,
        catalog_topic_id=PydanticObjectId(),
        plan_scope="catalog",
        items=[],
    )

    class FakePlanRepo:
        async def get_by_id(self, pid):
            return plan if pid == plan_id else None

    session = _session_stub(
        progression_session_plan_id=plan_id,
        pedagogy_session_recall_done=True,
        pedagogy_cluster_intro_done_for=0,
        pedagogy_cluster_curiosity_done_for=-1,
    )
    session.save = AsyncMock()
    svc = PedagogyRecallCuriosityService(plan_repo=FakePlanRepo())
    svc._cluster_curiosity_applies = AsyncMock(return_value=True)  # type: ignore[method-assign]
    svc._generate_cluster_curiosity_question = AsyncMock(  # type: ignore[method-assign]
        return_value="Why do plants need sunlight?"
    )
    result = await svc.maybe_emit(session, action=None)
    assert result is not None
    assert result["type"] == "cluster_curiosity_prompt"
    assert session.flow_state == "pedagogy_cluster_curiosity"


@pytest.mark.asyncio
async def test_cluster_curiosity_done_advances():
    session = _session_stub(
        pedagogy_session_recall_done=True,
        pedagogy_cluster_intro_done_for=0,
        flow_state="pedagogy_cluster_curiosity_feedback",
    )
    session.save = AsyncMock()
    svc = PedagogyRecallCuriosityService()
    done = await svc.maybe_emit(session, action="cluster_curiosity_done")
    assert done is None
    assert session.pedagogy_cluster_curiosity_done_for == 0
