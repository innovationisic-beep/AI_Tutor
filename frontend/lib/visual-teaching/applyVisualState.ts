import type { VisualState, VisualStatePatch } from "./types";
import { emptyVisualState } from "./types";

/**
 * Field-replace merge matching backend `apply_visual_state_patch`:
 * - omitted field → preserve
 * - supplied field → replace complete field
 * - highlights/labels_visible/arrows: [] → clear
 * - pointer/zoom: null → clear
 */
export function applyVisualStatePatch(
  current: VisualState | null | undefined,
  patch: VisualStatePatch | null | undefined
): VisualState {
  const base: VisualState = current
    ? {
        highlights: [...(current.highlights ?? [])],
        pointer: current.pointer ?? null,
        labels_visible: [...(current.labels_visible ?? [])],
        dim_others: Boolean(current.dim_others),
        zoom: current.zoom ? { region_id: current.zoom.region_id } : null,
        arrows: [...(current.arrows ?? [])],
      }
    : emptyVisualState();

  if (!patch) return base;

  if ("highlights" in patch) {
    base.highlights = Array.isArray(patch.highlights) ? [...patch.highlights] : [];
  }
  if ("labels_visible" in patch) {
    base.labels_visible = Array.isArray(patch.labels_visible)
      ? [...patch.labels_visible]
      : [];
  }
  if ("arrows" in patch) {
    base.arrows = Array.isArray(patch.arrows) ? [...patch.arrows] : [];
  }
  if ("dim_others" in patch) {
    base.dim_others = Boolean(patch.dim_others);
  }
  if ("pointer" in patch) {
    base.pointer =
      patch.pointer == null || patch.pointer === ""
        ? null
        : String(patch.pointer);
  }
  if ("zoom" in patch) {
    if (patch.zoom == null) {
      base.zoom = null;
    } else if (typeof patch.zoom === "object") {
      const rid = String(patch.zoom.region_id || "").trim();
      base.zoom = rid ? { region_id: rid } : null;
    } else {
      base.zoom = null;
    }
  }
  return base;
}
