import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import {
  CYCLE_CLOUD_TEXT_INSET_X,
  CYCLE_CLOUD_TEXT_INSET_Y,
  CYCLE_RING_CARD_WIDTH,
  measureCycleRingCardHeight,
  type AnnotationProjection,
  type ViewportBox,
} from "@/lib/instruction-timeline-v3/teaching/teachingClusters";

export type CycleCloudPlacement = "above" | "below" | "outside_left" | "outside_right";

export type CycleCloudLayoutContext = {
  width: number;
  height: number;
  nodeIds: string[];
  nodeBoxes: Map<string, ViewportBox>;
  cycleCenter: { cx: number; cy: number };
};

const CLOUD_ATTACH_GAP = 18;
const CLOUD_ABOVE_GAP = 24;
const CLOUD_COLLISION_GAP = 12;
const MAX_CLOUD_NUDGE_STEPS = 28;
const OWNER_CLEARANCE = 10;

function boxesOverlap(a: ViewportBox, b: ViewportBox, gap = CLOUD_COLLISION_GAP): boolean {
  return (
    a.x < b.x + b.w + gap &&
    a.x + a.w + gap > b.x &&
    a.y < b.y + b.h + gap &&
    a.y + a.h + gap > b.y
  );
}

export type PlacedCycleCloud = {
  projectionId: string;
  ownerId: string;
  placement: CycleCloudPlacement;
  nodeBox: ViewportBox;
  box: ViewportBox;
};

function cloneAnn(a: AnnotationProjection, box: ViewportBox): AnnotationProjection {
  return { ...a, viewport_box: { ...box } };
}

function clampCloudBox(
  box: ViewportBox,
  placement: CycleCloudPlacement,
  width: number,
  height: number,
): ViewportBox {
  const w = Math.min(box.w, width - 24);
  const h = Math.min(box.h, height - 24);
  const x = Math.max(12, Math.min(box.x, width - w - 12));
  let y = box.y;
  if (placement === "above") {
    // Prefer staying above the node over forcing y >= 12 (top clouds may clip slightly).
    y = Math.min(y, height - h - 12);
    y = Math.max(-h * 0.12, y);
  } else {
    y = Math.max(12, Math.min(y, height - h - 12));
  }
  return { x, y, w, h };
}

function enforceOwnerNodeClearance(entry: PlacedCycleCloud): void {
  const { nodeBox, placement } = entry;
  let { box } = entry;
  const gap =
    placement === "above"
      ? CLOUD_ABOVE_GAP
      : CLOUD_ATTACH_GAP;

  switch (placement) {
    case "above":
      if (box.y + box.h + OWNER_CLEARANCE > nodeBox.y) {
        box = { ...box, y: nodeBox.y - gap - box.h };
      }
      break;
    case "below":
      if (box.y < nodeBox.y + nodeBox.h + OWNER_CLEARANCE) {
        box = { ...box, y: nodeBox.y + nodeBox.h + gap };
      }
      break;
    case "outside_left":
      if (box.x + box.w + OWNER_CLEARANCE > nodeBox.x) {
        box = { ...box, x: nodeBox.x - gap - box.w };
      }
      break;
    case "outside_right":
      if (box.x < nodeBox.x + nodeBox.w + OWNER_CLEARANCE) {
        box = { ...box, x: nodeBox.x + nodeBox.w + gap };
      }
      break;
  }
  entry.box = box;
}

/** Polar quadrant: vertical halves → above/below; horizontal sides → outside ring. */
export function resolveCycleCloudPlacement(
  nodeCenterX: number,
  nodeCenterY: number,
  cycleCenter: { cx: number; cy: number },
): CycleCloudPlacement {
  const dx = nodeCenterX - cycleCenter.cx;
  const dy = nodeCenterY - cycleCenter.cy;
  if (Math.abs(dy) > Math.abs(dx) * 0.82) {
    return dy < 0 ? "above" : "below";
  }
  return dx < 0 ? "outside_left" : "outside_right";
}

export function placeCycleCloudBox(
  nodeBox: ViewportBox,
  cloudW: number,
  cloudH: number,
  placement: CycleCloudPlacement,
): ViewportBox {
  const ncx = nodeBox.x + nodeBox.w / 2;
  const ncy = nodeBox.y + nodeBox.h / 2;
  const gap =
    placement === "above"
      ? CLOUD_ABOVE_GAP
      : CLOUD_ATTACH_GAP;
  switch (placement) {
    case "above":
      return { x: ncx - cloudW / 2, y: nodeBox.y - gap - cloudH, w: cloudW, h: cloudH };
    case "below":
      return { x: ncx - cloudW / 2, y: nodeBox.y + nodeBox.h + gap, w: cloudW, h: cloudH };
    case "outside_left":
      return { x: nodeBox.x - gap - cloudW, y: ncy - cloudH / 2, w: cloudW, h: cloudH };
    case "outside_right":
      return { x: nodeBox.x + nodeBox.w + gap, y: ncy - cloudH / 2, w: cloudW, h: cloudH };
  }
}

/** Push cloud farther from ring center (never toward the core). */
function nudgeCloudAwayFromCenter(
  box: ViewportBox,
  nodeBox: ViewportBox,
  cycleCenter: { cx: number; cy: number },
  amount: number,
): ViewportBox {
  const ncx = nodeBox.x + nodeBox.w / 2;
  const ncy = nodeBox.y + nodeBox.h / 2;
  const ccx = box.x + box.w / 2;
  const ccy = box.y + box.h / 2;
  const distCloud = Math.hypot(ccx - cycleCenter.cx, ccy - cycleCenter.cy);
  const distNode = Math.hypot(ncx - cycleCenter.cx, ncy - cycleCenter.cy);
  if (distCloud >= distNode - 2) return box;
  const ux = ccx - cycleCenter.cx || ncx - cycleCenter.cx;
  const uy = ccy - cycleCenter.cy || ncy - cycleCenter.cy;
  const len = Math.hypot(ux, uy) || 1;
  return {
    ...box,
    x: box.x + (ux / len) * amount,
    y: box.y + (uy / len) * amount,
  };
}

function nudgeAlongPlacement(
  box: ViewportBox,
  placement: CycleCloudPlacement,
  dx: number,
  dy: number,
): ViewportBox {
  switch (placement) {
    case "above":
      return { ...box, y: box.y + dy };
    case "below":
      return { ...box, y: box.y + dy };
    case "outside_left":
      return { ...box, x: box.x + dx };
    case "outside_right":
      return { ...box, x: box.x + dx };
  }
}

function separationVector(a: ViewportBox, b: ViewportBox): { dx: number; dy: number } {
  const acx = a.x + a.w / 2;
  const acy = a.y + a.h / 2;
  const bcx = b.x + b.w / 2;
  const bcy = b.y + b.h / 2;
  let dx = acx - bcx;
  let dy = acy - bcy;
  const len = Math.hypot(dx, dy) || 1;
  dx /= len;
  dy /= len;
  return { dx, dy };
}

export function resolveCycleCloudCollisions(
  placed: PlacedCycleCloud[],
  ctx: CycleCloudLayoutContext,
): void {
  for (let step = 0; step < MAX_CLOUD_NUDGE_STEPS; step += 1) {
    let moved = false;

    for (const entry of placed) {
      const outward = nudgeCloudAwayFromCenter(entry.box, entry.nodeBox, ctx.cycleCenter, 6);
      if (outward.x !== entry.box.x || outward.y !== entry.box.y) {
        entry.box = outward;
        moved = true;
      }
    }

    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        const a = placed[i]!;
        const b = placed[j]!;
        if (!boxesOverlap(a.box, b.box, CLOUD_COLLISION_GAP)) continue;
        const { dx, dy } = separationVector(a.box, b.box);
        const push = 8 + step * 0.5;
        a.box = nudgeAlongPlacement(a.box, a.placement, dx * push * 0.5, dy * push * 0.5);
        b.box = nudgeAlongPlacement(b.box, b.placement, -dx * push * 0.5, -dy * push * 0.5);
        moved = true;
      }
    }

    for (const entry of placed) {
      for (const [nid, node] of ctx.nodeBoxes) {
        if (nid === entry.ownerId) continue;
        if (!boxesOverlap(entry.box, node, 6)) continue;
        const { dx, dy } = separationVector(entry.box, node);
        entry.box = nudgeAlongPlacement(
          entry.box,
          entry.placement,
          dx * 10,
          dy * 10,
        );
        moved = true;
      }
    }

    if (!moved) break;
  }

  for (const entry of placed) {
    enforceOwnerNodeClearance(entry);
    entry.box = clampCloudBox(entry.box, entry.placement, ctx.width, ctx.height);
    enforceOwnerNodeClearance(entry);
  }
}

/** Inner text rect inset from callout bounding box. */
export function cycleCloudContentRect(
  box: ViewportBox,
  height: number,
): ViewportBox {
  return {
    x: box.x + CYCLE_CLOUD_TEXT_INSET_X,
    y: box.y + CYCLE_CLOUD_TEXT_INSET_Y,
    w: Math.max(80, box.w - CYCLE_CLOUD_TEXT_INSET_X * 2),
    h: Math.max(40, height - CYCLE_CLOUD_TEXT_INSET_Y * 2),
  };
}

export function cycleCloudAttachmentPoint(
  box: ViewportBox,
  placement: CycleCloudPlacement,
): { x: number; y: number } {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  switch (placement) {
    case "above":
      return { x: cx, y: box.y + box.h - 4 };
    case "below":
      return { x: cx, y: box.y + 4 };
    case "outside_left":
      return { x: box.x + box.w - 4, y: cy };
    case "outside_right":
      return { x: box.x + 4, y: cy };
  }
}

export function cycleCloudNodeAnchor(
  nodeBox: ViewportBox,
  placement: CycleCloudPlacement,
): { x: number; y: number } {
  const cx = nodeBox.x + nodeBox.w / 2;
  const cy = nodeBox.y + nodeBox.h / 2;
  switch (placement) {
    case "above":
      return { x: cx, y: nodeBox.y + 2 };
    case "below":
      return { x: cx, y: nodeBox.y + nodeBox.h - 2 };
    case "outside_left":
      return { x: nodeBox.x + 2, y: cy };
    case "outside_right":
      return { x: nodeBox.x + nodeBox.w - 2, y: cy };
  }
}

/** Map placement onto annotation metadata for renderer (read-only hint). */
export function withCycleCloudPlacementMeta(
  ann: AnnotationProjection,
  placement: CycleCloudPlacement,
): AnnotationProjection {
  return {
    ...ann,
    teaching_hints: {
      ...(ann.teaching_hints ?? {}),
      cycle_cloud_placement: placement,
    },
  };
}

export function cycleCloudPlacementFromProjection(
  ann: AnnotationProjection,
): CycleCloudPlacement | null {
  const p = ann.teaching_hints?.cycle_cloud_placement;
  if (p === "above" || p === "below" || p === "outside_left" || p === "outside_right") {
    return p;
  }
  return null;
}

/**
 * Cycle-ring cloud callouts: one cloud per node, positioned by polar quadrant.
 * Replaces the legacy below-ring grid layout.
 */
export function composeCycleCloudAnnotations(
  annotations: AnnotationProjection[],
  ctx: CycleCloudLayoutContext,
): AnnotationProjection[] {
  if (annotations.length === 0) return annotations;

  const byOwner = new Map<string, AnnotationProjection[]>();
  for (const ann of annotations) {
    if (!ann.target_id) continue;
    const list = byOwner.get(ann.target_id) ?? [];
    list.push(ann);
    byOwner.set(ann.target_id, list);
  }

  const placed: PlacedCycleCloud[] = [];

  for (const ownerId of ctx.nodeIds) {
    const nodeBox = ctx.nodeBoxes.get(ownerId);
    const anns = byOwner.get(ownerId);
    if (!nodeBox || !anns?.length) continue;

    const ncx = nodeBox.x + nodeBox.w / 2;
    const ncy = nodeBox.y + nodeBox.h / 2;
    const placement = resolveCycleCloudPlacement(ncx, ncy, ctx.cycleCenter);

    for (const ann of anns) {
      const cloudW = CYCLE_RING_CARD_WIDTH;
      const cloudH = measureCycleRingCardHeight(ann.text ?? "", cloudW);
      let box = placeCycleCloudBox(nodeBox, cloudW, cloudH, placement);
      box = nudgeCloudAwayFromCenter(box, nodeBox, ctx.cycleCenter, 10);
      const draft: PlacedCycleCloud = {
        projectionId: ann.projection_id,
        ownerId,
        placement,
        nodeBox,
        box,
      };
      enforceOwnerNodeClearance(draft);
      box = clampCloudBox(draft.box, placement, ctx.width, ctx.height);

      placed.push({
        projectionId: ann.projection_id,
        ownerId,
        placement,
        nodeBox,
        box,
      });
    }
  }

  resolveCycleCloudCollisions(placed, ctx);

  const boxById = new Map(placed.map((p) => [p.projectionId, p.box]));
  const placementById = new Map(placed.map((p) => [p.projectionId, p.placement]));

  return annotations.map((ann) => {
    const box = boxById.get(ann.projection_id);
    const placement = placementById.get(ann.projection_id);
    if (box && placement) {
      return withCycleCloudPlacementMeta(cloneAnn(ann, box), placement);
    }
    return ann;
  });
}
