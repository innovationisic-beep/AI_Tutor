import type { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import type { ProjectionDiff, ProjectionSnapshot, RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

function sortById(items: RenderProjection[]): RenderProjection[] {
  return [...items].sort((a, b) => a.projection_id.localeCompare(b.projection_id));
}

export function computeProjectionDiff(
  prev: ProjectionSnapshot | null,
  next: ProjectionSnapshot,
  eventBus?: RuntimeEventBus,
): ProjectionDiff {
  if (!prev) {
    const added = sortById(next.projections);
    const diff: ProjectionDiff = {
      added,
      removed: [],
      updated: [],
      unchanged: [],
    };
    eventBus?.emit({
      type: "projection_diff_computed",
      added: diff.added.length,
      removed: 0,
      updated: 0,
      unchanged: 0,
      at: next.generated_at,
    });
    return diff;
  }

  const prevById = new Map(prev.projections.map((p) => [p.projection_id, p]));
  const nextById = new Map(next.projections.map((p) => [p.projection_id, p]));

  const added: RenderProjection[] = [];
  const removed: RenderProjection[] = [];
  const updated: RenderProjection[] = [];
  const unchanged: RenderProjection[] = [];

  for (const [id, curr] of nextById.entries()) {
    const before = prevById.get(id);
    if (!before) {
      added.push(curr);
      continue;
    }
    if (before.projection_hash !== curr.projection_hash) {
      updated.push(curr);
    } else {
      unchanged.push(curr);
    }
  }

  for (const [id, before] of prevById.entries()) {
    if (!nextById.has(id)) removed.push(before);
  }

  const diff: ProjectionDiff = {
    added: sortById(added),
    removed: sortById(removed),
    updated: sortById(updated),
    unchanged: sortById(unchanged),
  };

  eventBus?.emit({
    type: "projection_diff_computed",
    added: diff.added.length,
    removed: diff.removed.length,
    updated: diff.updated.length,
    unchanged: diff.unchanged.length,
    at: next.generated_at,
  });

  return diff;
}
