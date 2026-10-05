import type { ProjectionDiff, RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export type ProjectionTransitionState = "entering" | "stable" | "updating" | "exiting";

export interface ProjectionTransitionRecord {
  projection_id: string;
  state: ProjectionTransitionState;
}

export function buildTransitionStateMap(
  diff: ProjectionDiff,
  current: RenderProjection[],
): Record<string, ProjectionTransitionRecord> {
  const stateMap: Record<string, ProjectionTransitionRecord> = {};
  diff.added.forEach((p) => {
    stateMap[p.projection_id] = { projection_id: p.projection_id, state: "entering" };
  });
  diff.updated.forEach((p) => {
    stateMap[p.projection_id] = { projection_id: p.projection_id, state: "updating" };
  });
  diff.removed.forEach((p) => {
    stateMap[p.projection_id] = { projection_id: p.projection_id, state: "exiting" };
  });
  current.forEach((p) => {
    if (!stateMap[p.projection_id]) {
      stateMap[p.projection_id] = { projection_id: p.projection_id, state: "stable" };
    }
  });
  return stateMap;
}
