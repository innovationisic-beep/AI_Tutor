"""CIR v1 → native InstructionTimelineV3 dict (uses ``TimelinePlannerV3``)."""

from __future__ import annotations

import logging
from typing import Any

from app.services.timeline_planner_v3 import TimelinePlannerResult, TimelinePlannerV3

logger = logging.getLogger(__name__)


def _count_ops_in_timeline(tl: dict[str, Any]) -> int:
    n = 0
    for b in tl.get("beats") or []:
        if isinstance(b, dict):
            n += len(b.get("operations") or [])
    return n


def compile_cir_v1_to_timeline(
    *,
    cir: dict[str, Any],
    session_id: str,
    topic_id: str | None,
    concept: str,
    planner: TimelinePlannerV3 | None = None,
    from_llm: bool = False,
) -> TimelinePlannerResult:
    """
    Compile validated CIR JSON into the same timeline envelope as ``plan()``.

    Call ``validate_cir_v1`` first; invalid documents must fall back elsewhere.
    """
    pl = planner or TimelinePlannerV3()
    rep = str((cir or {}).get("representation_type") or "?")
    n_beats = len((cir or {}).get("beats") or [])
    n_nodes = len((cir or {}).get("nodes") or [])
    try:
        result = pl.compile_cir_v1_to_timeline(
            cir=cir,
            session_id=session_id,
            topic_id=topic_id,
            concept=concept,
            from_llm=from_llm,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[CIR_COMPILE_FAILED] reason=%s representation_type=%s beats_in_cir=%d nodes_in_cir=%d",
            str(exc)[:500],
            rep,
            n_beats,
            n_nodes,
        )
        raise
    tl = result.timeline
    ops = _count_ops_in_timeline(tl) if isinstance(tl, dict) else 0
    tid = str((tl or {}).get("timeline_id") or "")[:36]
    beats_out = len((tl or {}).get("beats") or []) if isinstance(tl, dict) else 0
    logger.info(
        "[CIR_COMPILE] planner_source=%s representation_type=%s beats=%d ops=%d timeline_id=%s",
        result.planner_source,
        rep,
        beats_out,
        ops,
        tid,
    )
    return result
