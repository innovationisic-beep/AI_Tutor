import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { HighlightEntity, HighlightEntityOp, SceneEntity } from "@/lib/instruction-timeline-v3/types";

/** Pedagogical emphasis phase — distinct from entity deletion (nodes/edges stay visible). */
export type HighlightEmphasis = "active" | "retired";

export const HIGHLIGHT_EMPHASIS_ACTIVE: HighlightEmphasis = "active";
export const HIGHLIGHT_EMPHASIS_RETIRED: HighlightEmphasis = "retired";

export function isHighlightEntity(entity: SceneEntity): entity is HighlightEntity {
  return entity.entity_type === "Highlight";
}

export function highlightEmphasis(entity: HighlightEntity): HighlightEmphasis {
  const raw = entity.semantic?.payload?.emphasis;
  return raw === HIGHLIGHT_EMPHASIS_RETIRED ? HIGHLIGHT_EMPHASIS_RETIRED : HIGHLIGHT_EMPHASIS_ACTIVE;
}

export function highlightTtlMs(entity: HighlightEntity): number | null {
  const raw = entity.semantic?.payload?.ttl_ms;
  return typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : null;
}

/**
 * Retire all currently active highlight overlays before a new pedagogical focus.
 * Underlying target nodes remain active and visible.
 */
export function retireActiveHighlights(
  entitiesById: Record<string, SceneEntity>,
  retiredByOp: string,
): void {
  for (const [entityId, entity] of Object.entries(entitiesById)) {
    if (!isHighlightEntity(entity)) continue;
    if (entity.lifecycle.state !== "active") continue;
    if (highlightEmphasis(entity) === HIGHLIGHT_EMPHASIS_RETIRED) continue;

    entitiesById[entityId] = {
      ...entity,
      semantic: {
        ...entity.semantic,
        payload: {
          ...(entity.semantic.payload ?? {}),
          emphasis: HIGHLIGHT_EMPHASIS_RETIRED,
          retired_by_op: retiredByOp,
        },
      },
    };
  }
}

export function buildHighlightEntity(op: HighlightEntityOp): HighlightEntity {
  const payload: Record<string, unknown> = {
    emphasis: HIGHLIGHT_EMPHASIS_ACTIVE,
  };
  if (typeof op.payload.ttl_ms === "number" && op.payload.ttl_ms > 0) {
    payload.ttl_ms = op.payload.ttl_ms;
  }

  return {
    entity_id: op.payload.highlight_id,
    entity_type: "Highlight",
    kind: "primitive",
    version: 1,
    spatial: { x: 0, y: 0, w: 0, h: 0 },
    semantic: { role: "focus", payload },
    render: { layer: 100, style_token: op.payload.style_token ?? "concept-highlight" },
    lifecycle: {
      state: "active",
      created_by_op: op.operation_id,
    },
    target_ids: op.payload.target_ids,
  };
}

export type HighlightLifecycleSummary = {
  active_highlight_count: number;
  retired_highlight_count: number;
  current_focus_highlight: string | null;
  ttl_ms_by_highlight: Record<string, number>;
};

export function summarizeHighlightLifecycle(
  entitiesById: Record<string, SceneEntity>,
): HighlightLifecycleSummary {
  let active = 0;
  let retired = 0;
  let currentFocus: string | null = null;
  const ttl_ms_by_highlight: Record<string, number> = {};

  for (const entity of Object.values(entitiesById)) {
    if (!isHighlightEntity(entity)) continue;
    const emphasis = highlightEmphasis(entity);
    if (emphasis === HIGHLIGHT_EMPHASIS_ACTIVE) {
      active += 1;
      currentFocus = entity.entity_id;
    } else {
      retired += 1;
    }
    const ttl = highlightTtlMs(entity);
    if (ttl != null) {
      ttl_ms_by_highlight[entity.entity_id] = ttl;
    }
  }

  return {
    active_highlight_count: active,
    retired_highlight_count: retired,
    current_focus_highlight: currentFocus,
    ttl_ms_by_highlight,
  };
}

export function findHighlightOpForOperationId(
  beats: Array<{ operations?: Array<{ operation_id: string; op_type: string; payload?: unknown }> }>,
  operationId: string,
): HighlightEntityOp | null {
  for (const beat of beats) {
    for (const op of beat.operations ?? []) {
      if (op.operation_id !== operationId || op.op_type !== "highlight_entity") continue;
      return op as HighlightEntityOp;
    }
  }
  return null;
}

/** Count painted vs retired overlays from presentation projections (debug / observability). */
export function summarizeHighlightProjections(
  projections: RenderProjection[],
  ttlExpiredIds?: ReadonlySet<string>,
): HighlightLifecycleSummary & { ttl_expired: string[] } {
  let active = 0;
  let retired = 0;
  let currentFocus: string | null = null;
  const ttl_ms_by_highlight: Record<string, number> = {};
  const ttl_expired: string[] = [];

  for (const p of projections) {
    if (p.projection_kind !== "highlight") continue;
    const id = p.source_entity_id;
    if (ttlExpiredIds?.has(id)) {
      ttl_expired.push(id);
      retired += 1;
      continue;
    }
    if (p.emphasis_phase === "retired" || !p.visible) {
      retired += 1;
      continue;
    }
    active += 1;
    currentFocus = id;
  }

  return {
    active_highlight_count: active,
    retired_highlight_count: retired,
    current_focus_highlight: currentFocus,
    ttl_ms_by_highlight,
    ttl_expired,
  };
}
