"""Shared helpers for VTSE strategy builders."""

from __future__ import annotations

import hashlib

from app.vtse.models.plan import (
    BeatInteraction,
    PedagogicalRole,
    PacingMode,
    RevealScript,
    RevealStep,
    TeachingBeat,
)

from app.cir.limits import CIR_V1_MAX_NODES as CIR_MAX_NODES
from app.cir.limits import COMPARISON_MAX_ROW_PAIRS


def stable_plan_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"plan_{prefix}_{digest}"


def node_id(index: int) -> str:
    return f"node_{index + 1}"


def beat_id(index: int) -> str:
    return f"beat_{index:04d}"


def pacing_for_role(role: PedagogicalRole) -> PacingMode:
    mapping: dict[PedagogicalRole, PacingMode] = {
        "anchor": "deliver",
        "explain": "deliver",
        "reinforce": "reinforce",
        "emphasize": "visualize",
        "reflect": "reflect",
        "connect": "reinforce",
        "compare": "visualize",
        "close": "close",
    }
    return mapping.get(role, "deliver")


def reveal_script(
    focus_id: str,
    annotation_text: str | None,
    highlight_ids: list[str],
) -> RevealScript:
    steps: list[RevealStep] = [RevealStep(kind="show_node", node_id=focus_id)]
    if annotation_text:
        steps.append(RevealStep(kind="annotate", target_id=focus_id, text=annotation_text))
    for hid in highlight_ids:
        steps.append(RevealStep(kind="highlight", target_ids=[hid]))
    return RevealScript(steps=steps)


def make_beat(
    *,
    index: int,
    focus_id: str,
    role: PedagogicalRole,
    narration: str,
    annotation: str | None,
    highlight_ids: list[str],
    authoring_source: str,
    interaction: BeatInteraction | None = None,
    extra_metadata: dict | None = None,
) -> TeachingBeat:
    meta = {"authoring_source": authoring_source}
    if extra_metadata:
        meta.update(extra_metadata)
    return TeachingBeat(
        beat_id=beat_id(index),
        index=index,
        pedagogical_role=role,
        pacing_mode=pacing_for_role(role),
        focus_node_id=focus_id,
        narration_text=narration,
        annotation_text=annotation,
        highlight_node_ids=list(highlight_ids),
        reveal_script=reveal_script(focus_id, annotation, highlight_ids),
        interaction=interaction or BeatInteraction(),
        metadata=meta,
    )
