import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { ViewportBox } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";
import { wrapTeachingExplanationLines } from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";
import {
  TIMELINE_ANNOTATION_PAD,
  TIMELINE_EXPLANATION_LINE_HEIGHT,
  TIMELINE_NODE_FONT_PROCESS,
  timelineCharsPerLine,
  timelineCharWidthPx,
} from "@/lib/teachingTypography";

/** Storyboard lane geometry for process / flow teaching. */
export const PROCESS_STORYBOARD = {
  topPad: 12,
  rowGap: 48,
  /** Left edge of the step-label column (included in board fit bounds). */
  stepLabelColumnLeft: 12,
  stepLabelW: 76,
  centerNodeX: 108,
  /** Fixed lane width — labels wrap; height grows (do not shrink font). */
  centerNodeW: 196,
  /** Minimum node height for short single-line labels. */
  centerNodeH: 52,
  /** Horizontal/vertical padding inside the process node rect. */
  nodePadX: 12,
  nodePadY: 10,
  /** Line box for process node title (font 17 / handwriting). */
  nodeLineHeight: 22,
  explanationPadLeft: 20,
  explanationMinW: 280,
  edgeStub: 8,
} as const;

const PROCESS_EXPLANATION_LINE_HEIGHT = TIMELINE_EXPLANATION_LINE_HEIGHT;
const PROCESS_EXPLANATION_PAD = TIMELINE_ANNOTATION_PAD;
const PROCESS_EXPLANATION_BOTTOM_OUTSET = 4;
const WRAP_SAFETY_PX = 4;

export type ProcessStoryboardRowLayout = {
  nodeId: string;
  stepIndex: number;
  stepDisplayLabel: string;
  nodeBox: ViewportBox;
  stepLabelY: number;
  explanationBox: ViewportBox | null;
};

/** Inner text column width inside an explanation card. */
export function processStoryboardTextInnerWidth(explW: number): number {
  return Math.max(96, explW - PROCESS_EXPLANATION_PAD * 2 - WRAP_SAFETY_PX);
}

/** Line-wrap width in characters from explanation card pixel width. */
export function processStoryboardWrapChars(explW: number): number {
  return timelineCharsPerLine(explW, PROCESS_EXPLANATION_PAD, WRAP_SAFETY_PX);
}

export function wrapProcessExplanationLines(text: string, explW: number): string[] {
  const maxChars = processStoryboardWrapChars(explW);
  const words = text.trim().split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (next.length <= maxChars) cur = next;
    else {
      if (cur) lines.push(cur);
      cur = w.length > maxChars ? w.slice(0, maxChars) : w;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [text];
}

/** Pixel height for a storyboard explanation card (matches renderer line wrap). */
export function measureProcessExplanationHeight(text: string, explW: number): number {
  const lines = wrapTeachingExplanationLines(text, processStoryboardWrapChars(explW));
  const h = lines.length * PROCESS_EXPLANATION_LINE_HEIGHT + PROCESS_EXPLANATION_PAD * 2 + PROCESS_EXPLANATION_BOTTOM_OUTSET;
  return Math.max(64, h);
}

/** Max chars per line inside a process identity node (fixed width, no font shrink). */
export function processNodeLabelWrapChars(
  nodeW: number = PROCESS_STORYBOARD.centerNodeW,
): number {
  const { nodePadX } = PROCESS_STORYBOARD;
  const charPx = timelineCharWidthPx(TIMELINE_NODE_FONT_PROCESS);
  const inner = Math.max(48, nodeW - nodePadX * 2 - WRAP_SAFETY_PX);
  return Math.max(8, Math.floor(inner / charPx));
}

/** Word-wrap process node labels to fit the node width. */
export function wrapProcessNodeLabelLines(
  label: string,
  nodeW: number = PROCESS_STORYBOARD.centerNodeW,
): string[] {
  const maxChars = processNodeLabelWrapChars(nodeW);
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (next.length <= maxChars) cur = next;
    else {
      if (cur) lines.push(cur);
      cur = w.length > maxChars ? w.slice(0, maxChars) : w;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [label.trim() || ""];
}

/** Node box height for a process label (grows with wrapped lines; min = centerNodeH). */
export function measureProcessNodeHeight(
  label: string,
  nodeW: number = PROCESS_STORYBOARD.centerNodeW,
): number {
  const { centerNodeH, nodePadY, nodeLineHeight } = PROCESS_STORYBOARD;
  const lines = wrapProcessNodeLabelLines(label, nodeW);
  const contentH = lines.length * nodeLineHeight + nodePadY * 2;
  return Math.max(centerNodeH, contentH);
}

function processNodeIdentityLabel(
  nodeProj: Extract<RenderProjection, { projection_kind: "node" }> | undefined,
): string {
  if (!nodeProj) return "";
  const hints = nodeProj.teaching_hints as
    | { process_identity?: string }
    | undefined;
  const identity = hints?.process_identity?.trim();
  if (identity) return identity;
  return (nodeProj.label ?? "").trim();
}

export function processStoryboardExplanationX(width: number): number {
  const { centerNodeX, centerNodeW, explanationPadLeft } = PROCESS_STORYBOARD;
  return centerNodeX + centerNodeW + explanationPadLeft;
}

export function processStoryboardExplanationWidth(width: number): number {
  const x = processStoryboardExplanationX(width);
  return Math.max(PROCESS_STORYBOARD.explanationMinW, width - x - 16);
}

/** Extend fit bounds so step labels left of identity nodes stay on screen. */
export function extendProcessStoryboardFitBounds(
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
): { minX: number; minY: number; maxX: number; maxY: number } {
  return {
    ...bounds,
    minX: Math.min(bounds.minX, PROCESS_STORYBOARD.stepLabelColumnLeft),
  };
}

export function layoutProcessStoryboardRows(
  nodeIds: string[],
  annotations: Array<{ target_id?: string; text: string; annotation_phase?: string }>,
  width: number,
  nodesById: Map<string, Extract<RenderProjection, { projection_kind: "node" }>>,
): ProcessStoryboardRowLayout[] {
  const {
    topPad,
    rowGap,
    centerNodeX,
    centerNodeW,
  } = PROCESS_STORYBOARD;
  const explX = processStoryboardExplanationX(width);
  const explW = processStoryboardExplanationWidth(width);

  const annByTarget = new Map<string, typeof annotations>();
  for (const ann of annotations) {
    if (!ann.target_id) continue;
    const list = annByTarget.get(ann.target_id) ?? [];
    list.push(ann);
    annByTarget.set(ann.target_id, list);
  }

  const rows: ProcessStoryboardRowLayout[] = [];
  let yCursor = topPad;

  nodeIds.forEach((id, stepIndex) => {
    const nodeProj = nodesById.get(id);
    const stepDisplayLabel =
      (nodeProj?.teaching_hints as { step_display_label?: string } | undefined)?.step_display_label
      ?? `Step ${stepIndex + 1}`;

    const identityLabel = processNodeIdentityLabel(nodeProj);
    const nodeH = measureProcessNodeHeight(identityLabel || stepDisplayLabel, centerNodeW);

    const nodeBox: ViewportBox = {
      x: centerNodeX,
      y: yCursor,
      w: centerNodeW,
      h: nodeH,
    };

    let explanationBox: ViewportBox | null = null;
    let rowH = nodeH;

    const owned = annByTarget.get(id) ?? [];
    if (owned.length > 0) {
      const text = owned.map((a) => a.text).join(" ");
      const explH = measureProcessExplanationHeight(text, explW);
      explanationBox = {
        x: explX,
        y: yCursor,
        w: explW,
        h: explH,
      };
      rowH = Math.max(nodeH, explH);
    }

    rows.push({
      nodeId: id,
      stepIndex,
      stepDisplayLabel,
      nodeBox,
      stepLabelY: nodeBox.y + nodeBox.h / 2 + 4,
      explanationBox,
    });

    yCursor += rowH + rowGap;
  });

  return rows;
}

export function estimateProcessStoryboardHeight(
  nodeCount: number,
  annotations: Array<{ text: string; target_id?: string }>,
  width: number,
): number {
  const nodeIds = Array.from({ length: nodeCount }, (_, i) => `__estimate_${i}`);
  const rows = layoutProcessStoryboardRows(nodeIds, annotations, width, new Map());
  if (rows.length === 0) {
    return PROCESS_STORYBOARD.topPad + 48;
  }
  const last = rows[rows.length - 1];
  const bottom = last.explanationBox
    ? last.explanationBox.y + last.explanationBox.h
    : last.nodeBox.y + last.nodeBox.h;
  return bottom + PROCESS_STORYBOARD.rowGap + 16;
}
