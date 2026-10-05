import type { AnnotationPhase } from "@/lib/instruction-timeline-v3/annotationLifecycle";
import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { InstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  measureProcessExplanationHeight,
  processStoryboardExplanationWidth,
  processStoryboardWrapChars,
} from "@/lib/instruction-timeline-v3/teaching/processStoryboardLayout";
import { wrapTeachingExplanationLines } from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";
import {
  TIMELINE_ANNOTATION_PAD,
  TIMELINE_EXPLANATION_LINE_HEIGHT,
  timelineCharsPerLine,
} from "@/lib/teachingTypography";

/** Cycle callout card width (rounded rectangle). */
export const CYCLE_RING_CARD_WIDTH = 228;

/** Inner padding — sync with cycleCloudContentRect. */
export const CYCLE_CLOUD_TEXT_INSET_X = 14;
export const CYCLE_CLOUD_TEXT_INSET_Y = 14;

const CYCLE_CARD_LINE_HEIGHT = TIMELINE_EXPLANATION_LINE_HEIGHT;
const CYCLE_CARD_PAD = TIMELINE_ANNOTATION_PAD;
export const CYCLE_CARD_MIN_H = 88;

/** Pixel height for one cycle-ring explanation cloud (matches renderer wrap + line metrics). */
export function measureCycleRingCardHeight(
  text: string,
  cardW: number = CYCLE_RING_CARD_WIDTH,
): number {
  const innerW = Math.max(120, cardW - CYCLE_CLOUD_TEXT_INSET_X * 2);
  const lines = wrapTeachingExplanationLines(
    (text ?? "").trim() || " ",
    processStoryboardWrapChars(innerW),
  );
  return Math.max(
    CYCLE_CARD_MIN_H,
    lines.length * CYCLE_CARD_LINE_HEIGHT + CYCLE_CARD_PAD * 2 + CYCLE_CLOUD_TEXT_INSET_Y * 2 + 10,
  );
}

export type ViewportBox = { x: number; y: number; w: number; h: number };

export const ANN_PAD = 14;
export const ANN_STACK_GAP = 10;
export const CLUSTER_TAIL_PAD = 12;
const ANN_MAX_H = 140;

export type AnnotationProjection = Extract<RenderProjection, { projection_kind: "annotation" }>;

export type TeachingCluster = {
  ownerId: string;
  nodeBox: ViewportBox;
  annotations: AnnotationProjection[];
};

export function measureAnnotationSize(
  text: string | undefined,
  width: number,
  kind: InstructionalLayoutKind,
  nodeBox?: ViewportBox,
  phase: AnnotationPhase = "active",
): ViewportBox {
  if (phase === "transient") {
    return { x: 0, y: 0, w: Math.min(width - 32, 240), h: 30 };
  }
  if (phase === "compressed") {
    return { x: 0, y: 0, w: Math.min(width - 32, 300), h: 38 };
  }
  if (phase === "passive") {
    const base = measureAnnotationSize(text, width, kind, nodeBox, "active");
    // Hierarchy annotations must always show full text — never cap their height.
    if (kind === "hierarchy_root_children") return base;
    return { ...base, h: Math.min(base.h, 120) };
  }
  if (kind === "flow_vertical_process") {
    const explW = processStoryboardExplanationWidth(width);
    const h = measureProcessExplanationHeight(text ?? "", explW);
    return { x: 0, y: 0, w: explW, h };
  }
  const prose = (text ?? "").trim() || " ";
  const textLen = prose.length;
  let w = Math.min(width - 32, Math.max(220, Math.min(380, 12 * Math.min(32, Math.ceil(textLen / 28) + 2))));
  if (kind === "comparison_split" && nodeBox) {
    w = Math.max(160, nodeBox.w - 8);
    const maxChars = timelineCharsPerLine(w, TIMELINE_ANNOTATION_PAD);
    const lineCount = wrapTeachingExplanationLines(prose, maxChars).length;
    const h = TIMELINE_ANNOTATION_PAD * 2 + lineCount * TIMELINE_EXPLANATION_LINE_HEIGHT + 10;
    return { x: 0, y: 0, w, h };
  }
  if (kind === "hierarchy_root_children" && nodeBox) {
    w = nodeBox.w;
    const maxChars = timelineCharsPerLine(w, TIMELINE_ANNOTATION_PAD);
    const lineCount = wrapTeachingExplanationLines(prose, maxChars).length;
    const h = TIMELINE_ANNOTATION_PAD * 2 + lineCount * TIMELINE_EXPLANATION_LINE_HEIGHT + 10;
    return { x: 0, y: 0, w, h };
  }
  if (kind === "cycle_ring") {
    w = CYCLE_RING_CARD_WIDTH;
    const h = measureCycleRingCardHeight(text ?? "", w);
    return { x: 0, y: 0, w, h };
  }
  if (kind === "grouped_cluster" && nodeBox) {
    w = Math.max(180, nodeBox.w);
    const maxChars = timelineCharsPerLine(w, TIMELINE_ANNOTATION_PAD);
    const lineCount = wrapTeachingExplanationLines(prose, maxChars).length;
    const h = Math.min(
      ANN_MAX_H,
      TIMELINE_ANNOTATION_PAD * 2 + lineCount * TIMELINE_EXPLANATION_LINE_HEIGHT + 10,
    );
    return { x: 0, y: 0, w, h };
  }
  const maxChars = timelineCharsPerLine(w, TIMELINE_ANNOTATION_PAD);
  const lineCount = wrapTeachingExplanationLines(prose, maxChars).length;
  const h = Math.min(
    ANN_MAX_H,
    TIMELINE_ANNOTATION_PAD * 2 + lineCount * TIMELINE_EXPLANATION_LINE_HEIGHT + 10,
  );
  return { x: 0, y: 0, w, h };
}

/** Reserved vertical space below a node for its owned annotation stack (layout pre-pass). */
export function estimateAnnotationStackHeight(
  annotations: AnnotationProjection[],
  ownerId: string,
  width: number,
  kind: InstructionalLayoutKind,
  nodeBox?: ViewportBox,
): number {
  const owned = annotations
    .filter((a) => a.target_id === ownerId)
    .sort((a, b) => a.projection_id.localeCompare(b.projection_id));
  if (owned.length === 0) return 0;
  let total = ANN_PAD;
  for (const ann of owned) {
    total += measureAnnotationSize(ann.text, width, kind, nodeBox, ann.annotation_phase).h + ANN_STACK_GAP;
  }
  return total - ANN_STACK_GAP + CLUSTER_TAIL_PAD;
}

export function buildTeachingClusters(
  annotations: AnnotationProjection[],
  nodeBoxes: Map<string, ViewportBox>,
  nodeIds: string[],
): TeachingCluster[] {
  const byOwner = new Map<string, AnnotationProjection[]>();
  for (const ann of annotations) {
    const tid = ann.target_id;
    if (!tid || !nodeBoxes.has(tid)) continue;
    const list = byOwner.get(tid) ?? [];
    list.push(ann);
    byOwner.set(tid, list);
  }

  const clusters: TeachingCluster[] = [];
  for (const ownerId of nodeIds) {
    const nodeBox = nodeBoxes.get(ownerId);
    const owned = byOwner.get(ownerId);
    if (!nodeBox || !owned?.length) continue;
    owned.sort((a, b) => a.projection_id.localeCompare(b.projection_id));
    clusters.push({ ownerId, nodeBox, annotations: owned });
  }

  const orphans = annotations.filter((a) => !a.target_id || !nodeBoxes.has(a.target_id));
  for (const ann of orphans) {
    clusters.push({
      ownerId: ann.target_id ?? ann.projection_id,
      nodeBox: ann.viewport_box,
      annotations: [ann],
    });
  }

  return clusters;
}

export function clusterReadingOrder(cluster: TeachingCluster, nodeIds: string[]): number {
  const idx = nodeIds.indexOf(cluster.ownerId);
  return idx >= 0 ? idx : nodeIds.length + cluster.ownerId.charCodeAt(0);
}

export function ownerColumnBand(node: ViewportBox, margin = 12): { left: number; right: number } {
  return { left: node.x - margin, right: node.x + node.w + margin };
}

export function clampXToOwnerColumn(x: number, w: number, node: ViewportBox, margin = 12): number {
  const band = ownerColumnBand(node, margin);
  if (x < band.left) return band.left;
  if (x + w > band.right) return Math.max(band.left, band.right - w);
  return x;
}

export function ownerAnchorX(
  node: ViewportBox,
  annW: number,
  kind: InstructionalLayoutKind,
): number {
  if (kind === "comparison_split" || kind === "grouped_cluster") {
    return node.x + 4;
  }
  return node.x + (node.w - annW) / 2;
}

export function clusterBounds(node: ViewportBox, annBoxes: ViewportBox[]): ViewportBox {
  let minX = node.x;
  let minY = node.y;
  let maxX = node.x + node.w;
  let maxY = node.y + node.h;
  for (const b of annBoxes) {
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w);
    maxY = Math.max(maxY, b.y + b.h);
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

export function translateBoxes(boxes: ViewportBox[], dx: number, dy: number): ViewportBox[] {
  return boxes.map((b) => ({ ...b, x: b.x + dx, y: b.y + dy }));
}
