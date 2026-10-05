"""Visual Teaching plan + VisualState patch semantics."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.services.visual_teaching.capabilities import SUPPORTED_VISUAL_CAPABILITIES


class VisualState(BaseModel):
    highlights: List[str] = Field(default_factory=list)
    pointer: Optional[str] = None
    labels_visible: List[str] = Field(default_factory=list)
    dim_others: bool = False
    zoom: Optional[Dict[str, str]] = None  # {"region_id": "..."}
    arrows: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if isinstance(self.pointer, str) and not self.pointer.strip():
            object.__setattr__(self, "pointer", None)


class EnterEffect(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)


class BoardWriteDraft(BaseModel):
    source_sentence: str = Field(..., min_length=1, max_length=2000)
    text: str = Field(..., min_length=1, max_length=400)


class BoardWriteRuntime(BaseModel):
    sentence_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1, max_length=400)


class SemanticAnchorEvent(BaseModel):
    source_sentence: str = Field(default="", max_length=2000)
    sentence_index: Optional[int] = Field(default=None, ge=0)
    patch: Dict[str, Any] = Field(default_factory=dict)


class VisualTeachingBeat(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    visual_state: VisualState = Field(default_factory=VisualState)
    enter_effects: List[EnterEffect] = Field(default_factory=list)
    speak: str = Field(..., min_length=1, max_length=4000)
    writes: List[BoardWriteRuntime] = Field(default_factory=list)
    sentence_events: List[SemanticAnchorEvent] = Field(default_factory=list)


class VisualTeachingScene(BaseModel):
    asset_key: str = Field(..., min_length=1, max_length=64)
    beats: List[VisualTeachingBeat] = Field(default_factory=list)


class VisualTeachingPlan(BaseModel):
    version: int = 1
    language: str = "en"
    source: Literal["planner", "fixture"] = "planner"
    capabilities_used: List[str] = Field(default_factory=list)
    scenes: List[VisualTeachingScene] = Field(default_factory=list)


def empty_visual_state() -> VisualState:
    return VisualState()


def apply_visual_state_patch(
    current: VisualState | Dict[str, Any],
    patch: Dict[str, Any] | None,
) -> VisualState:
    """
    Field-replace merge:
    - omitted field → preserve
    - supplied field → replace complete field
    - highlights: [] → clear; pointer/zoom null → clear
    """
    base = (
        current
        if isinstance(current, VisualState)
        else VisualState.model_validate(current or {})
    )
    if not patch:
        return base.model_copy(deep=True)

    data = base.model_dump()
    allowed = {
        "highlights",
        "pointer",
        "labels_visible",
        "dim_others",
        "zoom",
        "arrows",
    }
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key in ("highlights", "labels_visible", "arrows"):
            data[key] = list(value or [])
        elif key == "dim_others":
            data[key] = bool(value)
        elif key in ("pointer",):
            # Empty string → null (FE/BE contract: only region_id or null)
            if value is None or (isinstance(value, str) and not str(value).strip()):
                data[key] = None
            else:
                data[key] = str(value).strip()
        elif key == "zoom":
            if value is None:
                data[key] = None
            elif isinstance(value, dict):
                rid = str(value.get("region_id") or "").strip()
                data[key] = {"region_id": rid} if rid else None
            else:
                data[key] = None
    # Normalize pointer on base if somehow empty
    if isinstance(data.get("pointer"), str) and not data["pointer"].strip():
        data["pointer"] = None
    return VisualState.model_validate(data)


def materialize_beat_states(
    beat: VisualTeachingBeat,
) -> Dict[int, VisualState]:
    """
    Materialize VisualState at beat_start (-1) and after each sentence_index
    that has a patch (and every index up to max event).
    """
    start = beat.visual_state.model_copy(deep=True)
    by_index: Dict[int, VisualState] = {-1: start}
    current = start
    events_by_si: Dict[int, List[Dict[str, Any]]] = {}
    for ev in beat.sentence_events or []:
        si = ev.sentence_index
        if si is None:
            continue
        events_by_si.setdefault(int(si), []).append(dict(ev.patch or {}))

    if not events_by_si:
        return by_index

    for si in range(0, max(events_by_si.keys()) + 1):
        for patch in events_by_si.get(si, []):
            current = apply_visual_state_patch(current, patch)
        by_index[si] = current.model_copy(deep=True)
    return by_index


def visual_state_at(
    beat: VisualTeachingBeat,
    *,
    sentence_index: int,
) -> VisualState:
    """Exact VisualState at scene/beat/sentence_index (sentence_index=-1 → beat start)."""
    snapshots = materialize_beat_states(beat)
    if sentence_index < 0:
        return snapshots[-1]
    # Walk forward: use latest snapshot at or before sentence_index
    best = snapshots[-1]
    for si in sorted(k for k in snapshots.keys() if k >= 0):
        if si <= sentence_index:
            best = snapshots[si]
        else:
            break
    return best


def capabilities_implied_by_state(state: VisualState | Dict[str, Any]) -> set[str]:
    s = state if isinstance(state, VisualState) else VisualState.model_validate(state or {})
    used: set[str] = set()
    if s.highlights:
        used.add("highlights")
    if s.pointer:
        used.add("pointer")
    if s.labels_visible:
        used.add("labels_visible")
    if s.dim_others:
        used.add("dim_others")
    if s.zoom:
        used.add("zoom")
    if s.arrows:
        used.add("arrows")
    return used


def capabilities_implied_by_plan(plan: VisualTeachingPlan) -> set[str]:
    used: set[str] = set(plan.capabilities_used or [])
    for scene in plan.scenes:
        for beat in scene.beats:
            used |= capabilities_implied_by_state(beat.visual_state)
            if beat.enter_effects:
                used.add("enter_effects")
            if beat.sentence_events:
                used.add("sentence_visual_patches")
                for ev in beat.sentence_events:
                    used |= capabilities_implied_by_state(
                        apply_visual_state_patch(empty_visual_state(), ev.patch)
                    )
    return used


def assert_capabilities_supported(used: set[str]) -> list[str]:
    return sorted(c for c in used if c not in SUPPORTED_VISUAL_CAPABILITIES)
