"""Strict CIR v1 validation (graph + cross references)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.cir.limits import CIR_V1_MAX_EDGES, CIR_V1_MAX_NODES
from app.cir.v1 import CanonicalInstructionalRepresentationV1


@dataclass(frozen=True)
class CIRValidationResult:
    ok: bool
    errors: tuple[str, ...]
    """Parsed model when ok is True."""
    cir: CanonicalInstructionalRepresentationV1 | None = None


def validate_cir_v1(raw: Any) -> CIRValidationResult:
    """
    Validate a CIR v1 document.

    On failure returns ok=False and human-readable errors — callers should
    fall back to the existing TimelinePlannerV3 template path (no session breakage).
    """
    errors: list[str] = []

    if raw is None:
        return CIRValidationResult(ok=False, errors=("CIR payload is null",), cir=None)

    if not isinstance(raw, dict):
        return CIRValidationResult(
            ok=False,
            errors=("CIR payload must be a JSON object",),
            cir=None,
        )

    try:
        cir = CanonicalInstructionalRepresentationV1.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", "invalid")
            errors.append(f"{loc}: {msg}" if loc else str(msg))
        return CIRValidationResult(ok=False, errors=tuple(errors), cir=None)

    if len(cir.nodes) > CIR_V1_MAX_NODES:
        return CIRValidationResult(
            ok=False,
            errors=(f"CIR v1 allows at most {CIR_V1_MAX_NODES} nodes",),
            cir=None,
        )
    if len(cir.edges) > CIR_V1_MAX_EDGES:
        return CIRValidationResult(
            ok=False,
            errors=(f"CIR v1 allows at most {CIR_V1_MAX_EDGES} edges",),
            cir=None,
        )

    node_ids = [n.id for n in cir.nodes]
    if len(node_ids) != len(set(node_ids)):
        dup = _find_duplicates(node_ids)
        return CIRValidationResult(
            ok=False,
            errors=(f"duplicate node id(s): {', '.join(sorted(dup))}",),
            cir=None,
        )

    node_set = set(node_ids)
    for i, e in enumerate(cir.edges):
        if e.from_ not in node_set:
            errors.append(f"edges[{i}].from unknown node {e.from_!r}")
        if e.to not in node_set:
            errors.append(f"edges[{i}].to unknown node {e.to!r}")

    n_nodes = len(cir.nodes)
    n_beats = len(cir.beats)
    if n_nodes != n_beats:
        errors.append(
            "CIR v1 Zone 1 compile contract requires len(nodes) == len(beats); "
            f"got nodes={n_nodes}, beats={n_beats}"
        )

    want_indices = set(range(n_beats)) if n_beats else set()
    idx_set = {b.index for b in cir.beats}
    if n_beats and idx_set != want_indices:
        errors.append(
            "beat index set must be exactly {0..n-1} with no gaps or extras; "
            f"expected {sorted(want_indices)!r} got {sorted(idx_set)!r}"
        )

    beat_ids = [b.beat_id for b in cir.beats]
    if len(beat_ids) != len(set(beat_ids)):
        dup = _find_duplicates(beat_ids)
        return CIRValidationResult(
            ok=False,
            errors=(f"duplicate beat_id(s): {', '.join(sorted(dup))}",),
            cir=None,
        )

    beat_set = set(beat_ids)
    beat_indices = [b.index for b in cir.beats]
    if len(beat_indices) != len(set(beat_indices)):
        dup = _find_duplicates(beat_indices)
        errors.append(f"duplicate beat index value(s): {sorted(dup)!r}")

    for i, b in enumerate(cir.beats):
        for hid in b.highlight_node_ids:
            if hid not in node_set:
                errors.append(
                    f"beats[{i}].highlight_node_ids references unknown node {hid!r}"
                )
        if b.focus_node_id is not None and b.focus_node_id not in node_set:
            errors.append(
                f"beats[{i}].focus_node_id references unknown node {b.focus_node_id!r}"
            )

    for i, seg in enumerate(cir.narration_segments):
        if seg.beat_id not in beat_set:
            errors.append(
                f"narration_segments[{i}].beat_id {seg.beat_id!r} not found in beats"
            )

    if cir.narration_segments:
        beats_with_seg = {s.beat_id for s in cir.narration_segments}
        missing = beat_set - beats_with_seg
        if missing:
            errors.append(
                "narration_segments must cover every beat when non-empty; "
                f"missing beat_id(s): {', '.join(sorted(missing))}"
            )

    if errors:
        return CIRValidationResult(ok=False, errors=tuple(errors), cir=None)

    return CIRValidationResult(ok=True, errors=(), cir=cir)


def _find_duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    dup: set[Any] = set()
    for v in values:
        if v in seen:
            dup.add(v)
        seen.add(v)
    return dup
