"""Zone 1: VTSE primary authoring path (template → CIR → timeline)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from beanie.odm.fields import PydanticObjectId

from app.services.handlers.zone1_timeline_finalize import (
    VTSE_AUTHORING_FAILED_SOURCE,
    VTSE_AUTHORING_PLANNER_SOURCE,
    finalize_zone1_tutor_payload,
)
from app.services.timeline_planner_v3 import TimelinePlannerResult, TimelinePlannerV3
from app.vtse.authoring.zone1 import try_zone1_vtse_authoring

CYCLE_VTSE_TEMPLATE: dict[str, Any] = {
    "strategy_id": "cycle_process",
    "version": 1,
    "payload": {
        "steps": [
            {"label": "Evaporation", "summary": "Water turns into vapor."},
            {"label": "Condensation", "summary": "Vapor forms clouds."},
            {"label": "Precipitation", "summary": "Water falls as rain."},
        ]
    },
}


def _session(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": PydanticObjectId(),
        "current_zone": 1,
        "topic_id": None,
        "current_cluster_index": 0,
        "zone1_timeline_cache": None,
        "zone1_board_cluster_index": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


async def test_water_cycle_uses_vtse_not_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authored cycle_process template → VTSE board (cycle_ring), never generic."""
    from app.vtse.authoring import zone1 as zone1_authoring

    real_try = try_zone1_vtse_authoring

    async def _try_with_cycle_template(**kwargs: Any) -> TimelinePlannerResult | None:
        kwargs["vtse_template"] = CYCLE_VTSE_TEMPLATE
        kwargs["rag_service"] = None  # outline-only; skip LLM expand
        return await real_try(**kwargs)

    monkeypatch.setattr(zone1_authoring, "try_zone1_vtse_authoring", _try_with_cycle_template)

    session = _session()
    out: dict = {"message": "The water cycle moves water through evaporation and rain."}
    await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Water Cycle",
        concept="hydrologic cycle",
        question="Explain the water cycle",
        planner=TimelinePlannerV3(),
        rag_service=MagicMock(),
        cir_rag_context="- Water evaporates\n- Clouds form\n- Rain falls",
    )
    assert out.get("planner_source") == VTSE_AUTHORING_PLANNER_SOURCE
    assert "cir_generic" not in str(out.get("planner_source") or "")
    dbg = out.get("cir_instruction_debug") or {}
    assert dbg.get("using_vtse_authoring") is True
    assert dbg.get("emergency_fallback_used") is False
    vtse = dbg.get("vtse") or {}
    assert vtse.get("selected_strategy") == "cycle_process" or vtse.get("strategy_id") == "cycle_process"
    lm = (out.get("instruction_timeline_v3") or {}).get("layout_metadata") or {}
    assert lm.get("layout_profile") == "cycle_ring"


async def test_vtse_authoring_none_yields_no_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """When authoring returns None, tutor text stays and no generic board is invented."""
    from app.vtse.authoring import zone1 as zone1_authoring

    async def _none(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(zone1_authoring, "try_zone1_vtse_authoring", _none)

    session = _session()
    msg = "A short opening about renormalization without a board template."
    out: dict = {"message": msg}
    await finalize_zone1_tutor_payload(
        session,
        out,
        beat_kind="opening",
        topic_name="Quantum field theory",
        concept="Renormalization",
        question="?",
        planner=TimelinePlannerV3(),
    )
    assert out.get("instruction_timeline_v3") is None
    assert out.get("message") == msg
    dbg = out.get("cir_instruction_debug") or {}
    assert dbg.get("timeline_attached") is False
    assert dbg.get("emergency_fallback_used") is not True
    assert "cir_generic" not in str(out.get("planner_source") or "")
    assert "cir_generic" not in str(dbg.get("planner_source") or "")
    assert (
        out.get("planner_source") == VTSE_AUTHORING_FAILED_SOURCE
        or dbg.get("planner_source") == VTSE_AUTHORING_FAILED_SOURCE
        or dbg.get("llm_skip_reason") in {"vtse_authoring_failed"}
    )
