"""Validate VisualTeachingPlan against frozen authored package + capabilities."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from app.services.speech_note_dual import (
    MAX_WRITE_CHARS,
    normalize_board_writes,
    split_spoken_sentences,
)
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    normalize_visual_teaching,
)
from app.services.visual_teaching.capabilities import (
    ALLOWED_ENTER_EFFECT_TYPES,
    SUPPORTED_VISUAL_CAPABILITIES,
    is_enter_effect_allowed,
)
from app.services.visual_teaching.plan_schema import (
    BoardWriteRuntime,
    EnterEffect,
    SemanticAnchorEvent,
    VisualState,
    VisualTeachingBeat,
    VisualTeachingPlan,
    VisualTeachingScene,
    assert_capabilities_supported,
    capabilities_implied_by_plan,
)

MAX_BEATS_PER_SCENE = 12
MAX_SPEAK_CHARS = 4000
MAX_SCENES = 8

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


class VisualTeachingPlanError(ValueError):
    """Planner payload violates the Visual Teaching contract."""


def _strip_fence(raw: str) -> str:
    return _JSON_FENCE_RE.sub("", str(raw or "").strip()).strip()


def parse_plan_json(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    text = _strip_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisualTeachingPlanError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VisualTeachingPlanError("plan root must be an object")
    return data


def _region_ids(pkg: ConceptVisualTeaching, asset_key: str) -> Set[str]:
    for img in pkg.images:
        if img.asset_key == asset_key:
            return {r.region_id for r in img.regions}
    return set()


def _connection_ids(pkg: ConceptVisualTeaching, asset_key: str) -> Set[str]:
    for img in pkg.images:
        if img.asset_key == asset_key:
            return {c.connection_id for c in img.connections}
    return set()


def _validate_visual_state(
    state: VisualState,
    *,
    region_ids: Set[str],
    connection_ids: Set[str],
) -> None:
    for rid in state.highlights:
        if rid not in region_ids:
            raise VisualTeachingPlanError(f"unknown highlight region_id '{rid}'")
    if state.pointer is not None and state.pointer not in region_ids:
        raise VisualTeachingPlanError(f"unknown pointer region_id '{state.pointer}'")
    for rid in state.labels_visible:
        if rid not in region_ids:
            raise VisualTeachingPlanError(f"unknown labels_visible region_id '{rid}'")
    if state.zoom is not None:
        rid = str((state.zoom or {}).get("region_id") or "")
        if rid not in region_ids:
            raise VisualTeachingPlanError(f"unknown zoom region_id '{rid}'")
    for cid in state.arrows:
        if cid not in connection_ids:
            raise VisualTeachingPlanError(f"unknown arrow connection_id '{cid}'")


def _validate_patch(
    patch: Dict[str, Any],
    *,
    region_ids: Set[str],
    connection_ids: Set[str],
) -> Dict[str, Any]:
    allowed = {
        "highlights",
        "pointer",
        "labels_visible",
        "dim_others",
        "zoom",
        "arrows",
    }
    out: Dict[str, Any] = {}
    for key, value in (patch or {}).items():
        if key not in allowed:
            raise VisualTeachingPlanError(f"unknown patch field '{key}'")
        out[key] = value
    # Validate via a temporary VisualState when fields are present
    probe = VisualState()
    if "highlights" in out:
        probe.highlights = list(out["highlights"] or [])
    if "pointer" in out:
        if out["pointer"] is None or (
            isinstance(out["pointer"], str) and not str(out["pointer"]).strip()
        ):
            out["pointer"] = None
            probe.pointer = None
        else:
            probe.pointer = str(out["pointer"]).strip()
            out["pointer"] = probe.pointer
    if "labels_visible" in out:
        probe.labels_visible = list(out["labels_visible"] or [])
    if "dim_others" in out:
        probe.dim_others = bool(out["dim_others"])
    if "zoom" in out:
        probe.zoom = out["zoom"]
    if "arrows" in out:
        probe.arrows = list(out["arrows"] or [])
    # Only check ids that were supplied
    if "highlights" in out:
        for rid in probe.highlights:
            if rid not in region_ids:
                raise VisualTeachingPlanError(f"unknown highlight region_id '{rid}'")
    if "pointer" in out and probe.pointer is not None and probe.pointer not in region_ids:
        raise VisualTeachingPlanError(f"unknown pointer region_id '{probe.pointer}'")
    if "labels_visible" in out:
        for rid in probe.labels_visible:
            if rid not in region_ids:
                raise VisualTeachingPlanError(f"unknown labels_visible region_id '{rid}'")
    if "zoom" in out and probe.zoom is not None:
        rid = str((probe.zoom or {}).get("region_id") or "")
        if rid and rid not in region_ids:
            raise VisualTeachingPlanError(f"unknown zoom region_id '{rid}'")
    if "arrows" in out:
        for cid in probe.arrows:
            if cid not in connection_ids:
                raise VisualTeachingPlanError(f"unknown arrow connection_id '{cid}'")
    return out


def validate_plan_payload(
    raw: dict,
    *,
    authored: ConceptVisualTeaching | dict | None,
    language: str = "en",
    source: str = "planner",
) -> VisualTeachingPlan:
    pkg = normalize_visual_teaching(authored)
    if pkg is None or not pkg.images:
        raise VisualTeachingPlanError("no authored Visual Teaching images")

    authored_keys = [img.asset_key for img in pkg.images]
    scenes_raw = list(raw.get("scenes") or [])
    if len(scenes_raw) != len(authored_keys):
        raise VisualTeachingPlanError(
            f"plan must include exactly {len(authored_keys)} scenes in authored order"
        )
    if len(scenes_raw) > MAX_SCENES:
        raise VisualTeachingPlanError("too many scenes")

    scenes: List[VisualTeachingScene] = []
    for i, scene_raw in enumerate(scenes_raw):
        if not isinstance(scene_raw, dict):
            raise VisualTeachingPlanError(f"scene {i} must be an object")
        asset_key = str(scene_raw.get("asset_key") or "").strip()
        if asset_key != authored_keys[i]:
            raise VisualTeachingPlanError(
                f"scene {i} asset_key must be '{authored_keys[i]}' (got '{asset_key}')"
            )
        region_ids = _region_ids(pkg, asset_key)
        connection_ids = _connection_ids(pkg, asset_key)
        beats_raw = list(scene_raw.get("beats") or [])
        if not beats_raw:
            raise VisualTeachingPlanError(f"scene '{asset_key}' needs ≥1 beat")
        if len(beats_raw) > MAX_BEATS_PER_SCENE:
            raise VisualTeachingPlanError(f"scene '{asset_key}' has too many beats")

        beats: List[VisualTeachingBeat] = []
        for bi, beat_raw in enumerate(beats_raw):
            if not isinstance(beat_raw, dict):
                raise VisualTeachingPlanError(f"beat {bi} must be an object")
            speak = str(beat_raw.get("speak") or "").strip()
            if not speak or len(speak) > MAX_SPEAK_CHARS:
                raise VisualTeachingPlanError(f"beat {bi} speak invalid")
            if language.lower().startswith("hinglish") and _DEVANAGARI_RE.search(speak):
                raise VisualTeachingPlanError("Devanagari not allowed for Hinglish")

            vs_raw = beat_raw.get("visual_state") or {}
            visual_state = VisualState.model_validate(vs_raw)
            _validate_visual_state(
                visual_state, region_ids=region_ids, connection_ids=connection_ids
            )

            enter_effects: List[EnterEffect] = []
            for e in beat_raw.get("enter_effects") or []:
                if not isinstance(e, dict):
                    continue
                effect = EnterEffect.model_validate(e)
                if not is_enter_effect_allowed(effect.type):
                    raise VisualTeachingPlanError(
                        f"unknown enter_effect type '{effect.type}'. "
                        f"Allowed: {', '.join(sorted(ALLOWED_ENTER_EFFECT_TYPES))}"
                    )
                enter_effects.append(effect)

            write_drafts = beat_raw.get("writes") or []
            mapped = normalize_board_writes(
                spoken_text=speak, raw_writes=write_drafts
            )
            runtime_writes: List[BoardWriteRuntime] = []
            for w in mapped:
                runtime_writes.append(
                    BoardWriteRuntime(
                        sentence_index=int(w["sentence_index"]),
                        text=str(w["text"])[:MAX_WRITE_CHARS],
                    )
                )

            sentences = split_spoken_sentences(speak)
            sentence_events: List[SemanticAnchorEvent] = []
            for ev in beat_raw.get("sentence_events") or []:
                if not isinstance(ev, dict):
                    continue
                patch = _validate_patch(
                    dict(ev.get("patch") or {}),
                    region_ids=region_ids,
                    connection_ids=connection_ids,
                )
                src = str(ev.get("source_sentence") or "").strip()
                si = ev.get("sentence_index")
                if si is None and src:
                    mapped_ev = normalize_board_writes(
                        spoken_text=speak,
                        raw_writes=[{"source_sentence": src, "text": "."}],
                    )
                    if mapped_ev:
                        si = mapped_ev[0]["sentence_index"]
                if si is None:
                    raise VisualTeachingPlanError(
                        "sentence_event missing resolvable source_sentence"
                    )
                si_i = int(si)
                if si_i < 0 or (sentences and si_i >= len(sentences)):
                    raise VisualTeachingPlanError(
                        f"sentence_event sentence_index {si_i} out of range"
                    )
                sentence_events.append(
                    SemanticAnchorEvent(
                        source_sentence=src,
                        sentence_index=si_i,
                        patch=patch,
                    )
                )

            beats.append(
                VisualTeachingBeat(
                    id=str(beat_raw.get("id") or f"beat_{bi + 1}")[:64],
                    visual_state=visual_state,
                    enter_effects=enter_effects,
                    speak=speak,
                    writes=runtime_writes,
                    sentence_events=sentence_events,
                )
            )
        scenes.append(VisualTeachingScene(asset_key=asset_key, beats=beats))

    declared = [str(c) for c in (raw.get("capabilities_used") or [])]
    plan = VisualTeachingPlan(
        version=int(raw.get("version") or 1),
        language=str(raw.get("language") or language),
        source=source if source in ("planner", "fixture") else "planner",  # type: ignore[arg-type]
        capabilities_used=declared,
        scenes=scenes,
    )
    implied = capabilities_implied_by_plan(plan)
    plan.capabilities_used = sorted(set(declared) | implied)
    bad = assert_capabilities_supported(set(plan.capabilities_used))
    if bad:
        raise VisualTeachingPlanError(
            f"unsupported capabilities: {', '.join(bad)}"
        )
    # Also reject if implied uses unsupported even when declared empty
    bad2 = assert_capabilities_supported(implied)
    if bad2:
        raise VisualTeachingPlanError(
            f"unsupported capabilities: {', '.join(bad2)}"
        )
    return plan


def build_fixture_plan(
    authored: ConceptVisualTeaching | dict,
    *,
    language: str = "en",
) -> VisualTeachingPlan:
    """Deterministic fixture plan for tests / Phase 2 without DeepSeek."""
    pkg = normalize_visual_teaching(authored)
    if pkg is None:
        raise VisualTeachingPlanError("empty authored package")
    scenes: List[VisualTeachingScene] = []
    for img in pkg.images:
        region_ids = [r.region_id for r in img.regions]
        first = region_ids[0] if region_ids else None
        second = region_ids[1] if len(region_ids) > 1 else first
        speak = (
            f"Look carefully at this diagram. "
            f"We will notice the important parts one by one."
        )
        vs = VisualState(
            highlights=[first] if first else [],
            pointer=first,
            labels_visible=[first] if first else [],
            dim_others=bool(first),
            zoom={"region_id": first} if first else None,
            arrows=[img.connections[0].connection_id] if img.connections else [],
        )
        events: List[SemanticAnchorEvent] = []
        if first and second and first != second:
            events.append(
                SemanticAnchorEvent(
                    source_sentence="We will notice the important parts one by one.",
                    sentence_index=1,
                    patch={"highlights": [second], "pointer": second},
                )
            )
        scenes.append(
            VisualTeachingScene(
                asset_key=img.asset_key,
                beats=[
                    VisualTeachingBeat(
                        id="beat_1",
                        visual_state=vs,
                        speak=speak,
                        writes=[
                            BoardWriteRuntime(
                                sentence_index=0,
                                text=img.teaching_purpose[:120]
                                or "Study this diagram",
                            )
                        ],
                        sentence_events=events,
                    )
                ],
            )
        )
    plan = VisualTeachingPlan(
        version=1,
        language=language,
        source="fixture",
        scenes=scenes,
    )
    plan.capabilities_used = sorted(capabilities_implied_by_plan(plan))
    bad = assert_capabilities_supported(set(plan.capabilities_used))
    if bad:
        raise VisualTeachingPlanError(
            f"fixture requires unsupported capabilities: {', '.join(bad)}"
        )
    return plan
