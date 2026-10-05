import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { InstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import { COMPARISON_CENTER_X_RATIO, CYCLE_RING_CY_RATIO } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import {
  composeCycleCloudAnnotations,
} from "@/lib/instruction-timeline-v3/teaching/cycleCloudLayout";
import {
  ANN_PAD,
  ANN_STACK_GAP,
  buildTeachingClusters,
  clampXToOwnerColumn,
  clusterBounds,
  clusterReadingOrder,
  measureAnnotationSize,
  ownerAnchorX,
  type AnnotationProjection,
  type TeachingCluster,
  type ViewportBox,
  translateBoxes,
} from "@/lib/instruction-timeline-v3/teaching/teachingClusters";

export type { ViewportBox } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";
export {
  ANN_PAD,
  estimateAnnotationStackHeight,
  measureAnnotationSize,
} from "@/lib/instruction-timeline-v3/teaching/teachingClusters";

const COLLISION_GAP = 10;
const VIEWPORT_MARGIN = 28;
const MAX_CLUSTER_SHIFT = 120;

export type AnnotationLane = "below_center" | "below_left" | "outside_radial";

export type CompositionContext = {
  kind: InstructionalLayoutKind;
  width: number;
  height: number;
  nodeIds: string[];
  nodeBoxes: Map<string, ViewportBox>;
  rootEntityId: string | null;
  cycleCenter: { cx: number; cy: number };
  comparisonCenterX: number;
};

function cloneAnn(a: AnnotationProjection, box: ViewportBox): AnnotationProjection {
  return { ...a, viewport_box: { ...box } };
}

export function boxesOverlap(a: ViewportBox, b: ViewportBox, gap = COLLISION_GAP): boolean {
  return (
    a.x < b.x + b.w + gap &&
    a.x + a.w + gap > b.x &&
    a.y < b.y + b.h + gap &&
    a.y + a.h + gap > b.y
  );
}

function clampBox(box: ViewportBox, width: number, height: number): ViewportBox {
  const w = Math.min(box.w, width - 24);
  const h = Math.min(box.h, height - 24);
  const x = Math.max(12, Math.min(box.x, width - w - 12));
  const y = Math.max(12, Math.min(box.y, height - h - 12));
  return { x, y, w, h };
}

/** Penalize placements on edge corridors (used only for rare fallback lanes). */
export function edgeCorridorPenalty(box: ViewportBox, ctx: CompositionContext): number {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  let penalty = 0;

  if (ctx.kind === "comparison_split") {
    if (Math.abs(cx - ctx.comparisonCenterX) < 36) penalty += 55;
  }

  if (ctx.kind === "hierarchy_root_children" && ctx.rootEntityId) {
    const root = ctx.nodeBoxes.get(ctx.rootEntityId);
    if (root) {
      const trunkX = root.x + root.w / 2;
      const trunkTop = root.y + root.h;
      const trunkBottom = trunkTop + 120;
      if (Math.abs(cx - trunkX) < 42 && cy > trunkTop - 8 && cy < trunkBottom) {
        penalty += 45;
      }
    }
  }

  if (ctx.kind === "cycle_ring") {
    const dist = Math.hypot(cx - ctx.cycleCenter.cx, cy - ctx.cycleCenter.cy);
    if (dist < 90) penalty += 35;
  }

  return penalty;
}

/** Ownership-first stack: annotations directly under their owner, same column band. */
function placeClusterStack(
  cluster: TeachingCluster,
  ctx: CompositionContext,
  lane: AnnotationLane = "below_center",
): ViewportBox[] {
  const node = cluster.nodeBox;
  let y = node.y + node.h + ANN_PAD;
  const boxes: ViewportBox[] = [];

  for (const ann of cluster.annotations) {
    const size = measureAnnotationSize(ann.text, ctx.width, ctx.kind, node, ann.annotation_phase);
    let w = size.w;
    let x = ownerAnchorX(node, w, ctx.kind);

    if (lane === "below_center") {
      x = node.x + (node.w - w) / 2;
    }

    if (lane === "outside_radial" && ctx.kind === "cycle_ring") {
      // Cycle ring annotations are handled by composeCycleRingAnnotations (grid layout).
      // This branch is a safety fallback only — center below node.
      x = node.x + (node.w - w) / 2;
    } else {
      x = clampXToOwnerColumn(x, w, node);
    }

    const placed = clampBox({ x, y, w, h: size.h }, ctx.width, ctx.height);
    boxes.push(placed);
    y = placed.y + placed.h + ANN_STACK_GAP;
  }

  return boxes;
}

function clusterOverlapsForeignNodes(
  bounds: ViewportBox,
  ownerId: string,
  ctx: CompositionContext,
): boolean {
  for (const [nid, node] of ctx.nodeBoxes) {
    if (nid === ownerId) continue;
    if (boxesOverlap(bounds, node, 4)) return true;
  }
  return false;
}

function clusterOverlapsPlaced(
  bounds: ViewportBox,
  placed: ViewportBox[],
): boolean {
  for (const p of placed) {
    if (boxesOverlap(bounds, p, 8)) return true;
  }
  return false;
}

/** Resolve inter-cluster collisions by shifting whole stacks (preserves internal cohesion). */
function resolveClusterCollisions(
  clusters: Array<{ cluster: TeachingCluster; boxes: ViewportBox[] }>,
  ctx: CompositionContext,
): void {
  const placed: ViewportBox[] = [];

  for (const entry of clusters) {
    const { cluster } = entry;
    let boxes = entry.boxes;
    let bounds = clusterBounds(cluster.nodeBox, boxes);

    for (let step = 0; step < 16; step += 1) {
      const foreignNode = clusterOverlapsForeignNodes(bounds, cluster.ownerId, ctx);
      const otherCluster = clusterOverlapsPlaced(bounds, placed);
      if (!foreignNode && !otherCluster) break;

      const dy = 14 + step * 2;
      boxes = translateBoxes(boxes, 0, dy);
      bounds = clusterBounds(cluster.nodeBox, boxes);
    }

    entry.boxes = boxes.map((b) => clampBox(b, ctx.width, ctx.height));
    placed.push(clusterBounds(cluster.nodeBox, entry.boxes));
  }
}

function tryFallbackLane(
  cluster: TeachingCluster,
  ctx: CompositionContext,
  occupied: ViewportBox[],
): ViewportBox[] | null {
  if (ctx.kind !== "cycle_ring") return null;

  const radial = placeClusterStack(cluster, ctx, "outside_radial");
  const bounds = clusterBounds(cluster.nodeBox, radial);
  if (clusterOverlapsForeignNodes(bounds, cluster.ownerId, ctx)) return null;
  for (const o of occupied) {
    if (boxesOverlap(bounds, o, 8)) return null;
  }
  if (edgeCorridorPenalty(bounds, ctx) > 80) return null;
  return radial;
}

/**
 * Cycle-ring cloud callouts: polar placement around each node (above / below / outside).
 */
function composeCycleRingAnnotations(
  annotations: AnnotationProjection[],
  ctx: CompositionContext,
): AnnotationProjection[] {
  return composeCycleCloudAnnotations(annotations, ctx);
}

/**
 * Cluster-based annotation composition: each node owns its explanation stack.
 */
export function composeAnnotations(
  annotations: AnnotationProjection[],
  ctx: CompositionContext,
): AnnotationProjection[] {
  // Cycle ring uses a dedicated grid layout below the ring to avoid all overlap issues.
  if (ctx.kind === "cycle_ring") {
    return composeCycleRingAnnotations(annotations, ctx);
  }

  const clusters = buildTeachingClusters(annotations, ctx.nodeBoxes, ctx.nodeIds);
  clusters.sort(
    (a, b) => clusterReadingOrder(a, ctx.nodeIds) - clusterReadingOrder(b, ctx.nodeIds),
  );

  const placedClusterBounds: ViewportBox[] = [];
  const resultById = new Map<string, ViewportBox>();

  const entries: Array<{ cluster: TeachingCluster; boxes: ViewportBox[] }> = [];

  for (const cluster of clusters) {
    let boxes = placeClusterStack(cluster, ctx, "below_center");
    let bounds = clusterBounds(cluster.nodeBox, boxes);

    if (
      clusterOverlapsForeignNodes(bounds, cluster.ownerId, ctx) ||
      clusterOverlapsPlaced(bounds, placedClusterBounds)
    ) {
      const fallback = tryFallbackLane(cluster, ctx, placedClusterBounds);
      if (fallback) boxes = fallback;
    }

    entries.push({ cluster, boxes });
    placedClusterBounds.push(clusterBounds(cluster.nodeBox, boxes));
  }

  resolveClusterCollisions(entries, ctx);

  for (const { cluster, boxes } of entries) {
    cluster.annotations.forEach((ann, i) => {
      if (boxes[i]) resultById.set(ann.projection_id, boxes[i]);
    });
  }

  return annotations.map((ann) => {
    const box = resultById.get(ann.projection_id);
    if (box) return cloneAnn(ann, box);
    const fallback = {
      x: ann.viewport_box.x,
      y: ann.viewport_box.y,
      w: Math.max(200, ann.viewport_box.w || 200),
      h: Math.max(48, ann.viewport_box.h || 52),
    };
    return cloneAnn(ann, clampBox(fallback, ctx.width, ctx.height));
  });
}

/** Merged node + owned annotation stacks for edge routing obstacles. */
export function clusterObstaclesFromProjections(
  projections: RenderProjection[],
  inflate = 14,
): ViewportBox[] {
  const nodes = projections.filter(
    (p): p is Extract<RenderProjection, { projection_kind: "node" }> => p.projection_kind === "node",
  );
  const annotations = projections.filter(
    (p): p is AnnotationProjection => p.projection_kind === "annotation",
  );
  const nodeById = new Map(nodes.map((n) => [n.source_entity_id, n.viewport_box]));
  const annsByOwner = new Map<string, ViewportBox[]>();

  for (const ann of annotations) {
    if (!ann.visible || !ann.target_id) continue;
    const list = annsByOwner.get(ann.target_id) ?? [];
    list.push(ann.viewport_box);
    annsByOwner.set(ann.target_id, list);
  }

  const obstacles: ViewportBox[] = [];
  for (const [ownerId, node] of nodeById) {
    const owned = annsByOwner.get(ownerId) ?? [];
    const bounds =
      owned.length > 0 ? clusterBounds(node, owned) : { ...node, w: node.w, h: node.h };
    obstacles.push({
      x: bounds.x - inflate,
      y: bounds.y - inflate,
      w: bounds.w + inflate * 2,
      h: bounds.h + inflate * 2,
    });
  }

  for (const ann of annotations) {
    if (!ann.visible || (ann.target_id && nodeById.has(ann.target_id))) continue;
    const b = ann.viewport_box;
    obstacles.push({
      x: b.x - inflate,
      y: b.y - inflate,
      w: b.w + inflate * 2,
      h: b.h + inflate * 2,
    });
  }

  return obstacles;
}

/** @deprecated Use clusterObstaclesFromProjections for edge routing. */
export function annotationObstaclesFromProjections(
  projections: RenderProjection[],
  inflate = 12,
): ViewportBox[] {
  return clusterObstaclesFromProjections(projections, inflate);
}

function pointInBox(px: number, py: number, box: ViewportBox): boolean {
  return px >= box.x && px <= box.x + box.w && py >= box.y && py <= box.y + box.h;
}

function sampleSegmentHitsObstacle(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  obstacles: ViewportBox[],
): number {
  let hits = 0;
  for (let t = 0.25; t <= 0.75; t += 0.25) {
    const px = x1 + (x2 - x1) * t;
    const py = y1 + (y2 - y1) * t;
    for (const ob of obstacles) {
      if (pointInBox(px, py, ob)) hits += 1;
    }
  }
  return hits;
}

/** Extra perpendicular bulge when edge samples pass through cluster reading regions. */
export function edgeObstacleBulge(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  obstacles: ViewportBox[],
): number {
  const hits = sampleSegmentHitsObstacle(x1, y1, x2, y2, obstacles);
  if (hits === 0) return 0;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  for (const ob of obstacles) {
    if (pointInBox(mx, my, ob)) {
      return 32 + Math.min(ob.w, ob.h) * 0.18 + hits * 8;
    }
  }
  return 18 + hits * 10;
}

/** Uniform scene shift — clusters move together (nodes + owned annotations). */
export function balanceSceneInViewport(
  projections: RenderProjection[],
  width: number,
  height: number,
  kind?: InstructionalLayoutKind,
): RenderProjection[] {
  const TOP_SAFE = 16;
  const BOTTOM_SAFE = 32;
  const SIDE_SAFE = 20;

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let sumX = 0;
  let sumY = 0;
  let count = 0;

  for (const p of projections) {
    if (!p.visible) continue;
    const b = p.viewport_box;
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w);
    maxY = Math.max(maxY, b.y + b.h);
    sumX += b.x + b.w / 2;
    sumY += b.y + b.h / 2;
    count += 1;
  }
  if (!Number.isFinite(minX) || count === 0) return projections;

  const contentCx = sumX / count;
  const contentCy = sumY / count;
  const viewCx = width / 2;
  const viewCy = height * 0.46;

  let shiftX = 0;
  let shiftY = 0;

  const dx = viewCx - contentCx;
  const dy = viewCy - contentCy;
  const preserveColumnLayout = kind === "comparison_split";
  const pinTopLayout =
    kind === "flow_vertical_process" || kind === "hierarchy_root_children";
  if (!preserveColumnLayout && !pinTopLayout && Math.abs(dx) > 24) {
    shiftX = Math.sign(dx) * Math.min(48, Math.abs(dx) * 0.35);
  }
  if (!pinTopLayout && Math.abs(dy) > 32) {
    shiftY = Math.sign(dy) * Math.min(56, Math.abs(dy) * 0.28);
  }
  if (pinTopLayout && minY > TOP_SAFE) {
    shiftY = TOP_SAFE - minY;
  }

  const contentW = maxX - minX;
  if (contentW > width - SIDE_SAFE * 2) {
    const excess = (contentW - (width - SIDE_SAFE * 2)) / 2;
    shiftX += (viewCx - contentCx > 0 ? 1 : -1) * Math.min(24, excess);
  }

  const limitBottom = height - BOTTOM_SAFE;
  let deltaUp = maxY > limitBottom ? maxY - limitBottom : 0;
  const roomAbove = Math.max(0, minY - TOP_SAFE);
  deltaUp = Math.min(deltaUp, roomAbove);
  shiftY -= deltaUp;

  shiftX = Math.max(-MAX_CLUSTER_SHIFT, Math.min(MAX_CLUSTER_SHIFT, shiftX));
  shiftY = Math.max(-MAX_CLUSTER_SHIFT, Math.min(MAX_CLUSTER_SHIFT, shiftY));

  if (shiftX === 0 && shiftY === 0) return projections;

  return projections.map((p) =>
    p.visible
      ? {
          ...p,
          viewport_box: {
            ...p.viewport_box,
            x: p.viewport_box.x + shiftX,
            y: p.viewport_box.y + shiftY,
          },
        }
      : p,
  );
}

export function buildCompositionContext(
  kind: InstructionalLayoutKind,
  width: number,
  height: number,
  nodeIds: string[],
  nodeBoxMap: Map<string, ViewportBox>,
): CompositionContext {
  return {
    kind,
    width,
    height,
    nodeIds,
    nodeBoxes: nodeBoxMap,
    rootEntityId: kind === "hierarchy_root_children" ? (nodeIds[0] ?? null) : null,
    cycleCenter: { cx: width / 2, cy: height * CYCLE_RING_CY_RATIO },
    comparisonCenterX: width * COMPARISON_CENTER_X_RATIO,
  };
}
