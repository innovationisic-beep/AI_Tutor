import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export type ProcessStepPhase = "focus" | "completed" | "neutral";

/** Sort entity ids like node_1, node_2, … numerically when possible. */
export function sortProcessNodeIds(ids: string[]): string[] {
  return [...ids].sort((a, b) => {
    const ma = a.match(/^node_(\d+)$/);
    const mb = b.match(/^node_(\d+)$/);
    if (ma && mb) return Number(ma[1]) - Number(mb[1]);
    return a.localeCompare(b);
  });
}

export function processNodeIdsFromProjections(projections: RenderProjection[]): string[] {
  return sortProcessNodeIds(
    projections
      .filter((p): p is Extract<RenderProjection, { projection_kind: "node" }> => p.projection_kind === "node")
      .map((p) => p.source_entity_id),
  );
}

export function resolveProcessStepPhase(
  entityId: string,
  focusEntityId: string | null,
  orderedNodeIds: readonly string[],
): ProcessStepPhase {
  if (!focusEntityId) {
    if (orderedNodeIds[0] === entityId) return "focus";
    return "neutral";
  }
  if (entityId === focusEntityId) return "focus";
  const focusIdx = orderedNodeIds.indexOf(focusEntityId);
  const selfIdx = orderedNodeIds.indexOf(entityId);
  if (focusIdx >= 0 && selfIdx >= 0 && selfIdx < focusIdx) return "completed";
  return "neutral";
}

export function processNodeOpacity(phase: ProcessStepPhase, teaching: boolean): number {
  if (!teaching) return 1;
  switch (phase) {
    case "focus":
      return 1;
    case "completed":
      return 0.82;
    default:
      return 0.94;
  }
}

export function processAnnotationVisible(
  phase: ProcessStepPhase,
  teaching: boolean,
): boolean {
  if (!teaching) return true;
  return phase === "focus" || phase === "completed";
}

export function processStepDisplayLabel(
  projection: Extract<RenderProjection, { projection_kind: "node" }>,
  stepIndex: number,
): string {
  const hint = projection.teaching_hints?.step_display_label;
  if (hint && hint.trim()) return hint.trim();
  return `Step ${stepIndex + 1}`;
}

export function processNodeDisplayLabel(
  projection: Extract<RenderProjection, { projection_kind: "node" }>,
): string {
  const identity = projection.teaching_hints?.process_identity?.trim();
  if (identity) return identity;
  return projection.label.trim();
}

export function processEdgeOpacity(
  fromId: string,
  toId: string,
  focusEntityId: string | null,
  orderedNodeIds: readonly string[],
  teaching: boolean,
): number {
  if (!teaching || !focusEntityId) return 0.9;
  const focusIdx = orderedNodeIds.indexOf(focusEntityId);
  const toIdx = orderedNodeIds.indexOf(toId);
  if (focusIdx < 0 || toIdx < 0) return 0.88;
  if (toIdx <= focusIdx) return 0.92;
  return 0.35;
}
