import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

/** Concise node identity for hierarchy tree layouts (explanation lives in annotations). */
export function hierarchyNodeDisplayLabel(
  projection: Extract<RenderProjection, { projection_kind: "node" }>,
): string {
  const identity = projection.teaching_hints?.hierarchy_identity?.trim();
  if (identity) return identity;
  const raw = projection.label.trim();
  if (raw.length <= 48) return raw;
  const words = raw.split(/\s+/);
  return words.slice(0, 6).join(" ");
}
