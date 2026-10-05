"""Stable authoring slots for VTSE image regions.

Slot keys follow the template text, not positional ``node_*`` ids.
"""

from __future__ import annotations

from typing import Any


def slot_token(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def step_slot_key(title: Any) -> str:
    return f"step:{slot_token(title)}"


def trait_slot_key(label: Any) -> str:
    return f"trait:{slot_token(label)}"


def row_slot_key(dimension: Any) -> str:
    return f"row:{slot_token(dimension)}"


def column_slot_key(label: Any) -> str:
    return f"column:{slot_token(label)}"


def make_vtse_slot(
    *,
    slot_kind: str,
    slot_key: str,
    slot_index: int,
    side: str = "",
    label: str = "",
    **extra: Any,
) -> dict[str, Any]:
    slot = {
        "slot_kind": slot_kind,
        "slot_key": slot_key,
        "slot_index": int(slot_index),
        "side": str(side or ""),
        "label": label,
    }
    slot.update(extra)
    return slot


def iter_vtse_slots(template: Any, *, concept_name: str = "") -> list[dict[str, Any]]:
    """Slots an author can bind, derived from the authored template."""
    if template is None:
        return []
    if isinstance(template, dict):
        strategy = str(template.get("strategy_id") or "")
        payload = template.get("payload") or {}
    else:
        strategy = str(getattr(template, "strategy_id", "") or "")
        payload = getattr(template, "payload", None) or {}
    if not isinstance(payload, dict):
        return []
    if strategy == "comparison_contrast":
        return _comparison_slots(payload)
    if strategy in ("linear_process", "cycle_process"):
        return _step_slots(payload)
    if strategy in ("hierarchy_concept_intro", "clustered_trait_list"):
        return _trait_slots(payload, concept_name=concept_name)
    return []


def _comparison_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    left = str(payload.get("left_label") or "").strip()
    right = str(payload.get("right_label") or "").strip()
    if left:
        slots.append(
            make_vtse_slot(
                slot_kind="column",
                slot_key=column_slot_key(left),
                slot_index=0,
                side="left",
                label=left,
            )
        )
    if right:
        slots.append(
            make_vtse_slot(
                slot_kind="column",
                slot_key=column_slot_key(right),
                slot_index=1,
                side="right",
                label=right,
            )
        )
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        dimension = str(row.get("dimension") or "Compare").strip() or "Compare"
        slots.append(
            make_vtse_slot(
                slot_kind="row",
                slot_key=row_slot_key(dimension),
                slot_index=index,
                side="left",
                label=f"{dimension} · left",
                left_detail=str(row.get("left_detail") or row.get("left") or ""),
                right_detail=str(row.get("right_detail") or row.get("right") or ""),
            )
        )
        slots.append(
            make_vtse_slot(
                slot_kind="row",
                slot_key=row_slot_key(dimension),
                slot_index=index,
                side="right",
                label=f"{dimension} · right",
                left_detail=str(row.get("left_detail") or row.get("left") or ""),
                right_detail=str(row.get("right_detail") or row.get("right") or ""),
            )
        )
        slots.append(
            make_vtse_slot(
                slot_kind="row",
                slot_key=row_slot_key(dimension),
                slot_index=index,
                side="both",
                label=f"{dimension} · both",
                left_detail=str(row.get("left_detail") or row.get("left") or ""),
                right_detail=str(row.get("right_detail") or row.get("right") or ""),
            )
        )
    return slots


def _step_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    slots: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if isinstance(step, str):
            label = step.strip()
        elif isinstance(step, dict):
            label = str(step.get("label") or step.get("title") or "").strip()
        else:
            continue
        if not label:
            continue
        slots.append(
            make_vtse_slot(
                slot_kind="step",
                slot_key=step_slot_key(label),
                slot_index=index,
                label=label,
            )
        )
    return slots


def _trait_slots(payload: dict[str, Any], *, concept_name: str) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    root = str(concept_name or "").strip()
    if root:
        slots.append(
            make_vtse_slot(
                slot_kind="trait",
                slot_key=trait_slot_key(root),
                slot_index=0,
                label=root,
            )
        )
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    if not steps and isinstance(payload.get("traits"), list):
        steps = payload.get("traits") or []
    for offset, step in enumerate(steps):
        if isinstance(step, str):
            label = step.strip()
        elif isinstance(step, dict):
            label = str(step.get("label") or step.get("title") or "").strip()
        else:
            continue
        if not label:
            continue
        slots.append(
            make_vtse_slot(
                slot_kind="trait",
                slot_key=trait_slot_key(label),
                slot_index=offset + 1,
                label=label,
            )
        )
    return slots


def binding_matches_slot(binding: dict[str, Any], slot: dict[str, Any]) -> bool:
    if str(binding.get("slot_key") or "") != str(slot.get("slot_key") or ""):
        return False
    try:
        if int(binding.get("slot_index")) != int(slot.get("slot_index")):
            return False
    except (TypeError, ValueError):
        return False
    side = str(binding.get("side") or "")
    slot_side = str(slot.get("side") or "")
    if not side or side == "both":
        return slot_side in ("", "both", side)
    return slot_side == side


def resolve_binding(binding: dict[str, Any], slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [slot for slot in slots if binding_matches_slot(binding, slot)]
