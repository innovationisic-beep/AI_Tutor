import { CycleCloudCallout } from "@/components/ai/timeline-v3/CycleCloudCallout";
import { TeachingExplanationText } from "@/components/ai/timeline-v3/TeachingExplanationText";
import {
  cycleCloudPlacementFromProjection,
  resolveCycleCloudPlacement,
} from "@/lib/instruction-timeline-v3/teaching/cycleCloudLayout";
import {
  cycleRingCenter,
  cycleRingEdgePath,
  resolveCycleRingEdgeAnchors,
} from "@/lib/instruction-timeline-v3/teaching/cycleRingEdgePath";
import { measureCycleRingCardHeight } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";
import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import {
  resolveSpeechDisplayText,
  type SpeechRevealState,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import { SpeechSyncedText } from "@/lib/instruction-timeline-v3/teaching/SpeechSyncedText";
import { RENDER_LAYER_ORDER } from "@/lib/instruction-timeline-v3/renderer/renderLayers";
import type { InstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching";
import {
  logEntityRender,
  logProjectionState,
  logSvgRender,
  logVisibleRender,
} from "@/lib/instruction-timeline-v3/renderer/rendererVisibility";
import {
  applyLayoutToLayers,
  BOARD_DISPLAY_PAD,
  BOARD_FIT_PADDING,
  HIERARCHY_BOARD_FIT_PADDING,
  PROCESS_BOARD_FIT_PADDING,
  boardDisplayFrame,
  comparisonDividerForNodes,
  comparisonSplitStageBounds,
  computeBoardFitTransformFromBounds,
  contentBoundsFromProjections,
  logBoardFit,
  mergeContentBounds,
  parseBoardFitTransform,
  type ContentBounds,
} from "@/lib/instruction-timeline-v3/teaching";
import {
  clusterObstaclesFromProjections,
  edgeObstacleBulge,
  type ViewportBox,
} from "@/lib/instruction-timeline-v3/teaching/sceneComposition";
import { ComparisonRowRendererView } from "@/lib/instruction-timeline-v3/teaching/ComparisonRowRendererView";
import {
  TIMELINE_ANNOTATION_FONT_COMPRESSED,
  TIMELINE_ANNOTATION_FONT_SIZE,
  TIMELINE_ANNOTATION_FONT_TRANSIENT,
  TIMELINE_ANNOTATION_LINE_HEIGHT,
  TIMELINE_ANNOTATION_LINE_HEIGHT_COMPRESSED,
  TIMELINE_ANNOTATION_LINE_HEIGHT_TRANSIENT,
  TIMELINE_ANNOTATION_PAD,
  TIMELINE_LABEL_FONT_SIZE,
  TIMELINE_NODE_FONT_DEFAULT,
  TIMELINE_NODE_FONT_PROCESS,
  TIMELINE_NODE_FONT_ROOT,
  TIMELINE_STEP_LABEL_FONT_SIZE,
  TIMELINE_SVG_TEXT_CLASS,
  TIMELINE_SVG_TEXT_CSS,
  TIMELINE_WRAP_CHARS_FALLBACK,
} from "@/lib/teachingTypography";
import {
  buildComparisonRowUnits,
  isComparisonRowAlignedProjection,
  reflowComparisonRowUnits,
  shouldUseComparisonRowRenderer,
} from "@/lib/instruction-timeline-v3/teaching/comparisonRowRenderer";
import {
  processAnnotationVisible,
  processEdgeOpacity,
  processNodeDisplayLabel,
  processNodeIdsFromProjections,
  processNodeOpacity,
  processStepDisplayLabel,
  resolveProcessStepPhase,
} from "@/lib/instruction-timeline-v3/teaching/flowProcessPresentation";
import { hierarchyNodeDisplayLabel } from "@/lib/instruction-timeline-v3/teaching/hierarchyBranchPresentation";
import {
  PROCESS_STORYBOARD,
  extendProcessStoryboardFitBounds,
  measureProcessExplanationHeight,
  processStoryboardWrapChars,
  wrapProcessNodeLabelLines,
} from "@/lib/instruction-timeline-v3/teaching/processStoryboardLayout";
import {
  teachingExplanationPlain,
  wrapTeachingExplanationLines,
} from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";
import { instructionLifecycleDebugEnabled } from "@/lib/learning/instructionLifecycle";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

type ProjectionMap = Record<string, RenderProjection>;

const MIN_NODE_W = 168;
const MIN_NODE_H = 72;
const MIN_EDGE_LEN = 18;
const DEBUG_CLAMP_X_MIN = 50;
const DEBUG_CLAMP_X_MAX = 700;
const DEBUG_CLAMP_Y_MIN = 50;
const DEBUG_CLAMP_Y_MAX = 500;
/**
 * Fit bbox must extend past the annotation rect: SVG text baselines leave descenders below the last
 * line, and `v3-card-shadow` paints below the card (`feDropShadow` dy/stdDeviation).
 */
const ANNOTATION_FIT_BOTTOM_OUTSET = 36;
/** Conservative line count when word-wrap produces fewer lines than long-token reality. */
const ANNOTATION_CHAR_WRAP_DENOM = 28;

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) {
    if (!b.has(id)) return false;
  }
  return true;
}

function isProcessStoryboardNode(
  projection: RenderProjection,
  layoutKind: InstructionalLayoutKind,
): boolean {
  return (
    layoutKind === "flow_vertical_process" &&
    projection.projection_kind === "node" &&
    projection.teaching_hints?.process_tier === "step"
  );
}

/** Stable fit bounds for process storyboard — use full lane layout, not staged visibility. */
function projectionsForBoardFit(
  allProjections: RenderProjection[],
  layoutKind: InstructionalLayoutKind,
): RenderProjection[] {
  if (layoutKind !== "flow_vertical_process") {
    return allProjections.filter((p) => p.visible);
  }
  const processNodeIds = new Set(processNodeIdsFromProjections(allProjections));
  return allProjections.filter((p) => {
    if (p.projection_kind === "node" && processNodeIds.has(p.source_entity_id)) return true;
    if (
      p.projection_kind === "annotation" &&
      p.target_id &&
      processNodeIds.has(p.target_id)
    ) {
      return true;
    }
    if (p.projection_kind === "edge") return p.visible;
    return p.visible;
  });
}

function nodeBox(
  projection: RenderProjection,
  layoutKind: InstructionalLayoutKind = "flow_left_right",
): { x: number; y: number; w: number; h: number } {
  const box = projection.viewport_box;
  if (isProcessStoryboardNode(projection, layoutKind)) {
    return { x: box.x, y: box.y, w: box.w, h: box.h };
  }
  return {
    x: box.x,
    y: box.y,
    w: Math.max(box.w, MIN_NODE_W),
    h: Math.max(box.h, MIN_NODE_H),
  };
}

function anchorBottomCenter(n: { x: number; y: number; w: number; h: number }): { x: number; y: number } {
  return { x: n.x + n.w / 2, y: n.y + n.h };
}

function anchorTopCenter(n: { x: number; y: number; w: number; h: number }): { x: number; y: number } {
  return { x: n.x + n.w / 2, y: n.y };
}

function anchorRightCenter(n: { x: number; y: number; w: number; h: number }): { x: number; y: number } {
  return { x: n.x + n.w, y: n.y + n.h / 2 };
}

function anchorLeftCenter(n: { x: number; y: number; w: number; h: number }): { x: number; y: number } {
  return { x: n.x, y: n.y + n.h / 2 };
}

function debugClampedBox(box: { x: number; y: number; w: number; h: number }): {
  x: number;
  y: number;
  w: number;
  h: number;
} {
  return {
    x: clamp(box.x, DEBUG_CLAMP_X_MIN, DEBUG_CLAMP_X_MAX),
    y: clamp(box.y, DEBUG_CLAMP_Y_MIN, DEBUG_CLAMP_Y_MAX),
    w: Math.max(200, box.w),
    h: Math.max(100, box.h),
  };
}

function wrapLines(text: string, maxChars: number): string[] {
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

/** Boundary point on a node box facing toward (targetX, targetY). */
function anchorOnBoxToward(
  box: { x: number; y: number; w: number; h: number },
  targetX: number,
  targetY: number,
): { x: number; y: number } {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const dx = targetX - cx;
  const dy = targetY - cy;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) {
    return { x: cx, y: box.y + box.h };
  }
  const ux = dx / len;
  const uy = dy / len;
  const hw = box.w / 2;
  const hh = box.h / 2;
  const scale = Math.min(Math.abs(hw / ux) || Infinity, Math.abs(hh / uy) || Infinity);
  return { x: cx + ux * scale, y: cy + uy * scale };
}

function curvedEdgePath(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  layoutKind: InstructionalLayoutKind,
  viewport?: { width: number; height: number },
  obstacles?: ViewportBox[],
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const extra = edgeObstacleBulge(x1, y1, x2, y2, obstacles ?? []);
  const perpLen = Math.hypot(dx, dy) || 1;
  const ox = (-dy / perpLen) * extra;
  const oy = (dx / perpLen) * extra;
  if (layoutKind === "cycle_ring" && viewport) {
    return cycleRingEdgePath(x1, y1, x2, y2, viewport);
  }
  if (layoutKind === "flow_vertical_process") {
    return `M ${x1} ${y1} L ${x2} ${y2}`;
  }
  if (layoutKind === "hierarchy_root_children") {
    // Elbow routing: straight down from root to mid-trunk, then straight across to child column, then down to child top
    const midY = y1 + Math.round((y2 - y1) * 0.48);
    return `M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`;
  }
  if (
    layoutKind === "flow_left_right" ||
    layoutKind === "comparison_split" ||
    layoutKind === "grouped_cluster"
  ) {
    const sag = Math.min(56, Math.max(14, Math.abs(dx) * 0.14)) + extra;
    const dir = dy >= 0 ? 1 : -1;
    const c1x = x1 + dx * 0.38 + ox;
    const c1y = y1 + sag * dir + oy;
    const c2x = x1 + dx * 0.62 + ox;
    const c2y = y2 - sag * dir + oy;
    return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
  }
  const sag = Math.min(48, Math.max(12, Math.abs(dy) * 0.12)) + extra * 0.5;
  const hdir = dx >= 0 ? 1 : -1;
  const c1x = x1 + sag * hdir + ox;
  const c1y = y1 + dy * 0.42 + oy;
  const c2x = x2 - sag * hdir + ox;
  const c2y = y1 + dy * 0.58 + oy;
  return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
}

function tightHighlightBox(
  projection: Extract<RenderProjection, { projection_kind: "highlight" }>,
  bySourceEntityId: ProjectionMap,
  pad: number,
  layoutKind: InstructionalLayoutKind,
): { x: number; y: number; w: number; h: number } | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const tid of projection.target_ids) {
    const np = bySourceEntityId[tid];
    if (!np || np.projection_kind !== "node") continue;
    const nb = nodeBox(np, layoutKind);
    minX = Math.min(minX, nb.x);
    minY = Math.min(minY, nb.y);
    maxX = Math.max(maxX, nb.x + nb.w);
    maxY = Math.max(maxY, nb.y + nb.h);
  }
  if (!Number.isFinite(minX)) return null;
  return {
    x: minX - pad,
    y: minY - pad,
    w: maxX - minX + pad * 2,
    h: maxY - minY + pad * 2,
  };
}

type FitBoxContext = {
  bySourceEntityId: ProjectionMap;
  presentation: "teaching" | "debug";
  layoutKind: InstructionalLayoutKind;
};

function annotationLineCount(
  text: string | undefined,
  teaching: boolean,
  boxW?: number,
): number {
  const t = text ?? "";
  if (boxW && boxW > 40) {
    return wrapTeachingExplanationLines(t, processStoryboardWrapChars(boxW)).length;
  }
  const wrapped = wrapTeachingExplanationLines(t, teaching ? TIMELINE_WRAP_CHARS_FALLBACK : 36);
  const density = Math.max(1, Math.ceil(t.length / ANNOTATION_CHAR_WRAP_DENOM));
  return Math.max(wrapped.length, density);
}

/**
 * Bounds used by {@link computeBoardFitTransform}: match rendered ink (nodes use {@link nodeBox},
 * highlights use {@link tightHighlightBox}, annotations use wrap + descender/shadow slack).
 */
function edgeInkBounds(
  projection: Extract<RenderProjection, { projection_kind: "edge" }>,
  bySourceEntityId: ProjectionMap,
  layoutKind: InstructionalLayoutKind,
  rootEntityId: string | null,
  viewport: { width: number; height: number },
): ContentBounds | null {
  const { x1, y1, x2, y2 } = resolveEdgeEndpoints(
    projection,
    bySourceEntityId,
    layoutKind,
    rootEntityId,
    viewport,
  );
  const pad = 12;
  return {
    minX: Math.min(x1, x2) - pad,
    minY: Math.min(y1, y2) - pad,
    maxX: Math.max(x1, x2) + pad,
    maxY: Math.max(y1, y2) + pad,
  };
}

function effectiveViewportBoxForFit(p: RenderProjection, ctx: FitBoxContext): {
  x: number;
  y: number;
  w: number;
  h: number;
} {
  const { bySourceEntityId, presentation, layoutKind } = ctx;
  if (p.projection_kind === "node" || p.projection_kind === "container") {
    return nodeBox(p, layoutKind);
  }
  if (p.projection_kind === "highlight") {
    const pad = presentation === "teaching" ? 5 : 4;
    const tight = tightHighlightBox(p, bySourceEntityId, pad, layoutKind);
    if (tight) return tight;
    return p.viewport_box;
  }
  if (p.projection_kind !== "annotation") return p.viewport_box;
  const teaching = presentation === "teaching";
  const phase = p.annotation_phase ?? "active";
  if (phase === "compressed" || phase === "transient") {
    const h = phase === "transient" ? 34 : 42;
    return { ...p.viewport_box, h: Math.max(p.viewport_box.h, h) };
  }
  if (layoutKind === "flow_vertical_process") {
    const h = measureProcessExplanationHeight(p.text ?? "", p.viewport_box.w);
    return { ...p.viewport_box, h: h + 8 };
  }
  if (layoutKind === "cycle_ring") {
    const h = measureCycleRingCardHeight(p.text ?? "", p.viewport_box.w);
    return { ...p.viewport_box, h: h + 10 };
  }
  const nLines = annotationLineCount(p.text, teaching, p.viewport_box.w);
  const lineHeight = teaching ? TIMELINE_ANNOTATION_LINE_HEIGHT : 17;
  const pad = teaching ? TIMELINE_ANNOTATION_PAD : 12;
  const h =
    Math.max(p.viewport_box.h, nLines * lineHeight + pad * 2) + ANNOTATION_FIT_BOTTOM_OUTSET;
  return { ...p.viewport_box, h };
}

/** Ink used to crop the SVG. Comparison stage bounds are not included. */
function laidOutInkBounds(
  projections: RenderProjection[],
  ctx: FitBoxContext,
  bySourceEntityId: ProjectionMap,
  rootEntityId: string | null,
  viewport: { width: number; height: number },
  includeInvisible: boolean,
): ContentBounds | null {
  const measured = projections.map((p) => ({
    ...p,
    viewport_box: effectiveViewportBoxForFit(p, ctx),
  }));
  let bounds = contentBoundsFromProjections(measured, { includeInvisible });
  for (const p of projections) {
    if (p.projection_kind !== "edge") continue;
    if (!includeInvisible && !p.visible) continue;
    bounds = mergeContentBounds(
      bounds,
      edgeInkBounds(p, bySourceEntityId, ctx.layoutKind, rootEntityId, viewport),
    );
  }
  return bounds;
}

function resolveEdgeEndpoints(
  projection: Extract<RenderProjection, { projection_kind: "edge" }>,
  bySourceEntityId: ProjectionMap,
  layoutKind: InstructionalLayoutKind,
  rootEntityId: string | null,
  viewport: { width: number; height: number },
): { x1: number; y1: number; x2: number; y2: number } {
  const fromProjection = bySourceEntityId[projection.from_id];
  const toProjection = bySourceEntityId[projection.to_id];

  if (fromProjection && toProjection && fromProjection.projection_kind === "node" && toProjection.projection_kind === "node") {
    const fromN = nodeBox(fromProjection, layoutKind);
    const toN = nodeBox(toProjection, layoutKind);
    let p1: { x: number; y: number };
    let p2: { x: number; y: number };
    if (layoutKind === "cycle_ring") {
      return resolveCycleRingEdgeAnchors(fromN, toN);
    } else if (layoutKind === "flow_left_right") {
      p1 = anchorRightCenter(fromN);
      p2 = anchorLeftCenter(toN);
    } else if (layoutKind === "grouped_cluster") {
      const fromCx = fromN.x + fromN.w / 2;
      const toCx = toN.x + toN.w / 2;
      const sameColumn = Math.abs(fromCx - toCx) < Math.min(fromN.w, toN.w) * 0.55;
      if (sameColumn) {
        if (fromN.y + fromN.h <= toN.y + 4) {
          p1 = anchorBottomCenter(fromN);
          p2 = anchorTopCenter(toN);
        } else {
          p1 = anchorTopCenter(fromN);
          p2 = anchorBottomCenter(toN);
        }
      } else if (fromCx < toCx) {
        p1 = anchorRightCenter(fromN);
        p2 = anchorLeftCenter(toN);
      } else {
        p1 = anchorLeftCenter(fromN);
        p2 = anchorRightCenter(toN);
      }
    } else if (layoutKind === "flow_vertical_process") {
      const stub = PROCESS_STORYBOARD.edgeStub;
      p1 = anchorBottomCenter(fromN);
      p2 = anchorTopCenter(toN);
      p1 = { x: p1.x, y: p1.y + stub };
      p2 = { x: p2.x, y: p2.y - stub };
    } else if (layoutKind === "comparison_split") {
      const midX = viewport.width / 2;
      const fromCx = fromN.x + fromN.w / 2;
      const toCx = toN.x + toN.w / 2;
      if (fromCx < midX && toCx > midX) {
        p1 = anchorRightCenter(fromN);
        p2 = anchorLeftCenter(toN);
      } else if (fromCx > midX && toCx < midX) {
        p1 = anchorLeftCenter(fromN);
        p2 = anchorRightCenter(toN);
      } else if (fromN.y + fromN.h / 2 <= toN.y + toN.h / 2) {
        p1 = anchorBottomCenter(fromN);
        p2 = anchorTopCenter(toN);
      } else {
        p1 = anchorTopCenter(fromN);
        p2 = anchorBottomCenter(toN);
      }
    } else if (layoutKind === "hierarchy_root_children") {
      // Always: root bottom-center → child top-center — clean elbow, no diagonal spaghetti
      p1 = anchorBottomCenter(fromN);
      p2 = anchorTopCenter(toN);
    } else {
      p1 = anchorBottomCenter(fromN);
      p2 = anchorTopCenter(toN);
    }
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const len = Math.hypot(dx, dy);
    if (len >= MIN_EDGE_LEN) {
      return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
    }
  }

  const box = projection.viewport_box;
  return {
    x1: box.x,
    y1: box.y,
    x2: box.x + Math.max(box.w, MIN_EDGE_LEN),
    y2: box.y + Math.max(box.h, MIN_EDGE_LEN),
  };
}

type RenderOpts = {
  bySourceEntityId: ProjectionMap;
  layoutKind: InstructionalLayoutKind;
  rootEntityId: string | null;
  edgeObstacles: ViewportBox[];
  viewport: { width: number; height: number };
  showDebugChrome: boolean;
  presentation: "teaching" | "debug";
  enterAnimIds: Set<string>;
  /** When false, entities render at full opacity (production whiteboard). */
  useEnterMotion: boolean;
  /** Currently emphasized entity (narration / operation focus). */
  focusEntityId: string | null;
  /** Presentation-only TTL expiry — hides overlay without mutating scene history. */
  ttlExpiredHighlightIds?: ReadonlySet<string>;
  speechRevealByEntityId?: Readonly<Record<string, SpeechRevealState>>;
  speechRevealEnabled?: boolean;
  processNodeIds?: readonly string[];
};

function renderProjection(projection: RenderProjection, opts: RenderOpts): JSX.Element | null {
  if (!projection.visible) {
    if (instructionLifecycleDebugEnabled()) {
      logEntityRender(projection, projection.viewport_box, { opacity: 0, painted: false });
    }
    return null;
  }
  const box = projection.viewport_box;
  const teaching = opts.presentation === "teaching";
  const enter = opts.useEnterMotion && opts.enterAnimIds.has(projection.projection_id);

  if (projection.projection_kind === "edge") {
    const p = resolveEdgeEndpoints(
      projection,
      opts.bySourceEntityId,
      opts.layoutKind,
      opts.rootEntityId,
      opts.viewport,
    );
    const d = curvedEdgePath(
      p.x1,
      p.y1,
      p.x2,
      p.y2,
      opts.layoutKind,
      opts.viewport,
      opts.edgeObstacles,
    );
    const isCycleClose = projection.source_entity_id === "edge_cycle_close";
    const stroke = teaching ? "#64748b" : "#334155";
    const strokeWidth =
      opts.layoutKind === "flow_vertical_process"
        ? teaching
          ? 1.45
          : 1.6
        : teaching
          ? isCycleClose
            ? 2.65
            : 2.25
          : isCycleClose
            ? 3.35
            : 3;
    if (instructionLifecycleDebugEnabled()) {
      logEntityRender(projection, box, { opacity: teaching ? 0.88 : 0.92, painted: true });
    }
    const edgeOpacity =
      opts.layoutKind === "flow_vertical_process" && opts.processNodeIds
        ? processEdgeOpacity(
            projection.from_id,
            projection.to_id,
            opts.focusEntityId,
            opts.processNodeIds,
            teaching,
          )
        : teaching
          ? 0.9
          : 0.92;
    return (
      <g key={projection.projection_id}>
        <path
          d={d}
          fill="none"
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          opacity={edgeOpacity}
          markerEnd={
            opts.layoutKind === "cycle_ring"
              ? "url(#v3-cycle-arrow)"
              : opts.layoutKind === "flow_vertical_process"
                ? "url(#v3-flow-arrow)"
                : undefined
          }
        />
        {opts.showDebugChrome ? (
          <text x={(p.x1 + p.x2) / 2} y={(p.y1 + p.y2) / 2 - 4} fontSize="9" fill="#64748b">
            edge
          </text>
        ) : null}
      </g>
    );
  }

  if (projection.projection_kind === "highlight") {
    if (
      opts.ttlExpiredHighlightIds?.has(projection.source_entity_id) ||
      projection.emphasis_phase === "retired"
    ) {
      return null;
    }
    const isActiveEmphasis = projection.emphasis_phase === "active";
    const pad = teaching ? 5 : 4;
    const tight =
      teaching && projection.target_ids.length > 0
        ? tightHighlightBox(projection, opts.bySourceEntityId, pad, opts.layoutKind)
        : null;
    const hb = tight ?? { x: box.x - pad, y: box.y - pad, w: box.w + pad * 2, h: box.h + pad * 2 };
    const rectProps = teaching
      ? {
          fill: "rgba(251, 191, 36, 0.06)",
          stroke: "rgba(245, 158, 11, 0.42)",
          strokeWidth: 1.75,
          filter: "url(#v3-highlight-glow)",
        }
      : {
          fill: "rgba(251, 191, 36, 0.14)",
          stroke: "rgba(245, 158, 11, 0.7)",
          strokeWidth: 2.5,
          filter: undefined,
        };
    return (
      <g key={projection.projection_id} opacity={teaching ? 0.92 : 0.85} className={teaching && enter ? "v3-highlight-enter" : undefined}>
        <rect
          x={hb.x}
          y={hb.y}
          width={hb.w}
          height={hb.h}
          rx={12}
          fill={rectProps.fill}
          stroke={rectProps.stroke}
          strokeWidth={rectProps.strokeWidth}
          filter={rectProps.filter}
        />
        {isActiveEmphasis && teaching ? (
          <animate attributeName="opacity" values="0.72;1;0.78;1" dur="2.8s" repeatCount="indefinite" />
        ) : isActiveEmphasis ? (
          <animate attributeName="opacity" values="0.45;1;0.45" dur="2.4s" repeatCount="indefinite" />
        ) : null}
      </g>
    );
  }

  if (projection.projection_kind === "node" || projection.projection_kind === "container") {
    const n = nodeBox(projection, opts.layoutKind);
    const isProcessStoryboard =
      teaching &&
      opts.layoutKind === "flow_vertical_process" &&
      projection.projection_kind === "node" &&
      projection.teaching_hints?.process_tier === "step";
    const processPhase =
      opts.layoutKind === "flow_vertical_process" && opts.processNodeIds
        ? resolveProcessStepPhase(
            projection.source_entity_id,
            opts.focusEntityId,
            opts.processNodeIds,
          )
        : null;
    const isRoot =
      !isProcessStoryboard &&
      opts.rootEntityId !== null &&
      projection.source_entity_id === opts.rootEntityId &&
      projection.projection_kind === "node";
    const isFocus =
      teaching &&
      projection.projection_kind === "node" &&
      (processPhase === "focus" ||
        (opts.layoutKind !== "flow_vertical_process" &&
          opts.focusEntityId !== null &&
          projection.source_entity_id === opts.focusEntityId));
    const dimNonFocus =
      teaching &&
      opts.focusEntityId !== null &&
      projection.projection_kind === "node" &&
      projection.source_entity_id !== opts.focusEntityId &&
      opts.layoutKind !== "flow_vertical_process";
    const nodeOpacity =
      processPhase !== null
        ? processNodeOpacity(processPhase, teaching)
        : dimNonFocus
          ? 0.83
          : 1;
    if (instructionLifecycleDebugEnabled()) {
      logEntityRender(projection, n, { opacity: nodeOpacity, painted: true });
    }
    const fill = teaching
      ? isRoot
        ? "rgba(248, 250, 252, 0.96)"
        : "rgba(239, 246, 255, 0.92)"
      : "rgba(59, 130, 246, 0.14)";
    let stroke = teaching ? (isRoot ? "#cbd5e1" : "#93c5fd") : "#1e40af";
    let sw = teaching ? 1.35 : 2;
    if (isFocus) {
      stroke = "#38bdf8";
      sw = teaching ? 2.1 : sw;
    } else if (processPhase === "completed") {
      stroke = teaching ? "#cbd5e1" : stroke;
      sw = teaching ? 1.15 : sw;
    }
    const stepIndex =
      typeof projection.teaching_hints?.sequence_index === "number"
        ? projection.teaching_hints.sequence_index
        : opts.processNodeIds?.indexOf(projection.source_entity_id) ?? 0;
    const rx = teaching ? (isProcessStoryboard ? 10 : 12) : 10;
    const titleSize = teaching
      ? isProcessStoryboard
        ? TIMELINE_NODE_FONT_PROCESS
        : isRoot
          ? TIMELINE_NODE_FONT_ROOT
          : TIMELINE_NODE_FONT_DEFAULT
      : 15;
    const titleWeight = teaching ? (isProcessStoryboard ? 600 : isRoot ? 700 : 600) : 700;
    const isHierarchyTree =
      opts.layoutKind === "hierarchy_root_children" && projection.projection_kind === "node";
    const nodeIdentityLabel = isProcessStoryboard
      ? processNodeDisplayLabel(projection)
      : isHierarchyTree
        ? hierarchyNodeDisplayLabel(projection)
        : projection.row_detail?.trim() || projection.label.trim();
    return (
      <g
        key={projection.projection_id}
        className={teaching && enter ? "v3-node-enter" : undefined}
        opacity={nodeOpacity}
      >
        {isProcessStoryboard ? (
          <text
            x={PROCESS_STORYBOARD.stepLabelColumnLeft + 4}
            y={n.y + n.h / 2 + 4}
            textAnchor="start"
            fontSize={TIMELINE_STEP_LABEL_FONT_SIZE}
            fontWeight={500}
            fill="#64748b"
            className="select-none"
          >
            {processStepDisplayLabel(projection, stepIndex)}
          </text>
        ) : null}
        <rect
          x={n.x}
          y={n.y}
          width={n.w}
          height={n.h}
          fill={fill}
          stroke={stroke}
          strokeWidth={sw}
          rx={rx}
          filter={teaching ? "url(#v3-node-shadow)" : "url(#v3-soft-shadow)"}
        />
        {"label" in projection ? (() => {
          const fullLabel = nodeIdentityLabel;
          const isCompareHeader =
            projection.teaching_hints?.comparison_tier === "header" ||
            String(projection.teaching_hints?.semantic_role ?? "")
              .toLowerCase()
              .includes("header");
          const speech = resolveSpeechDisplayText(
            fullLabel,
            opts.speechRevealByEntityId?.[projection.source_entity_id],
            Boolean(
              opts.speechRevealEnabled &&
                teaching &&
                !isCompareHeader &&
                !isProcessStoryboard &&
                !isHierarchyTree,
            ),
          );
          const visibleLabel = isCompareHeader
            ? fullLabel
            : speech.visibleText || (speech.phase === "pending" ? "" : fullLabel);
          if (!visibleLabel && speech.phase === "pending") {
            return null;
          }
          if (speech.activeSuffix && teaching) {
            return (
              <SpeechSyncedText
                passivePrefix={speech.passivePrefix}
                activeSuffix={speech.activeSuffix}
                phase={speech.phase}
                x={n.x + n.w / 2 - (fullLabel.length * titleSize * 0.26) / 2}
                y={n.y + n.h / 2 + 5}
                fontSize={titleSize}
                fontWeight={titleWeight}
              />
            );
          }
          if (isProcessStoryboard) {
            const lines = wrapProcessNodeLabelLines(visibleLabel, n.w);
            const lineH = PROCESS_STORYBOARD.nodeLineHeight;
            const blockH = lines.length * lineH;
            const startY = n.y + n.h / 2 - blockH / 2 + lineH * 0.72;
            return (
              <text
                x={n.x + n.w / 2}
                y={startY}
                textAnchor="middle"
                fontSize={titleSize}
                fontWeight={titleWeight}
                fill="#0f172a"
                className="select-none"
                opacity={speech.phase === "speaking" ? 0.95 : 1}
              >
                {lines.map((line, li) => (
                  <tspan
                    key={`pn-${projection.projection_id}-L${li}`}
                    x={n.x + n.w / 2}
                    dy={li === 0 ? 0 : lineH}
                  >
                    {line}
                  </tspan>
                ))}
              </text>
            );
          }
          return (
            <text
              x={n.x + n.w / 2}
              y={n.y + n.h / 2 + (teaching ? 5 : 5)}
              textAnchor="middle"
              fontSize={titleSize}
              fontWeight={titleWeight}
              fill={teaching ? "#0f172a" : "#0f172a"}
              className="select-none"
              opacity={speech.phase === "speaking" ? 0.95 : 1}
            >
              {visibleLabel}
            </text>
          );
        })() : null}
        {opts.showDebugChrome ? (
          <text x={n.x + 8} y={n.y + n.h - 8} fontSize="9" fill="#64748b">
            {projection.source_entity_id}
          </text>
        ) : null}
      </g>
    );
  }

  if (projection.projection_kind === "annotation") {
    const processPhase =
      opts.layoutKind === "flow_vertical_process" &&
      opts.processNodeIds &&
      projection.target_id
        ? resolveProcessStepPhase(
            projection.target_id,
            opts.focusEntityId,
            opts.processNodeIds,
          )
        : null;
    if (
      processPhase !== null &&
      !processAnnotationVisible(processPhase, teaching)
    ) {
      return null;
    }
    const phase = projection.annotation_phase ?? "active";
    const isHistoryPhase = phase === "compressed" || phase === "transient";
    const isHierarchyAnn = opts.layoutKind === "hierarchy_root_children";
    const isCycleAnn = opts.layoutKind === "cycle_ring";
    const isProcessStoryboardAnn =
      opts.layoutKind === "flow_vertical_process" && Boolean(projection.target_id);
    const isComparisonAnn = opts.layoutKind === "comparison_split";
    const isGroupedAnn = opts.layoutKind === "grouped_cluster";
    const rawText = isHistoryPhase
      ? compressedAnnotationDisplayText(projection.text, phase)
      : projection.text;
    const fullText = isHistoryPhase ? rawText : teachingExplanationPlain(rawText);
    const wrapExplanation = (t: string): string[] => {
      if (isHistoryPhase) return [t];
      const maxChars =
        isProcessStoryboardAnn ||
        isHierarchyAnn ||
        isCycleAnn ||
        isComparisonAnn ||
        isGroupedAnn
          ? processStoryboardWrapChars(box.w)
          : teaching
            ? TIMELINE_WRAP_CHARS_FALLBACK
            : 36;
      return wrapTeachingExplanationLines(t, maxChars);
    };
    const speech = resolveSpeechDisplayText(
      fullText,
      opts.speechRevealByEntityId?.[projection.source_entity_id],
      Boolean(opts.speechRevealEnabled && teaching && phase === "active"),
    );
    const visibleText =
      phase === "compressed" || phase === "transient"
        ? fullText
        : speech.visibleText || (speech.phase === "pending" ? "" : fullText);
    const layoutLines = wrapExplanation(fullText);
    const lines = visibleText ? wrapExplanation(visibleText) : [];
    const lineHeight =
      phase === "transient"
        ? TIMELINE_ANNOTATION_LINE_HEIGHT_TRANSIENT
        : phase === "compressed"
          ? TIMELINE_ANNOTATION_LINE_HEIGHT_COMPRESSED
          : teaching
            ? TIMELINE_ANNOTATION_LINE_HEIGHT
            : 17;
    const pad =
      phase === "transient" ? 8 : phase === "compressed" ? 10 : teaching ? TIMELINE_ANNOTATION_PAD : 12;
    const nLines = Math.max(lines.length, layoutLines.length);
    const contentH = nLines * lineHeight + pad * 2;
    const bottomOutset = phase === "active" || phase === "passive" ? ANNOTATION_FIT_BOTTOM_OUTSET : 4;
    const h =
      isCycleAnn
        ? Math.max(
            box.h,
            measureCycleRingCardHeight(fullText, box.w),
          )
        : opts.layoutKind === "flow_vertical_process" ||
            isHierarchyAnn ||
            isComparisonAnn ||
            isGroupedAnn
          ? Math.max(box.h, contentH + bottomOutset)
          : Math.max(box.h, contentH) + bottomOutset;
    const annDim =
      teaching &&
      opts.layoutKind !== "flow_vertical_process" &&
      !isHierarchyAnn &&
      opts.focusEntityId !== null &&
      projection.target_id !== undefined &&
      projection.target_id !== opts.focusEntityId;
    const phaseOpacity =
      phase === "active"
        ? 1
        : phase === "passive"
          ? opts.layoutKind === "flow_vertical_process"
            ? 0.84
            : 0.78
          : phase === "compressed"
            ? 0.68
            : 0.62;
    const groupOpacity = (annDim ? 0.86 : 1) * phaseOpacity;
    const fontSize =
      phase === "transient"
        ? TIMELINE_ANNOTATION_FONT_TRANSIENT
        : phase === "compressed"
          ? TIMELINE_ANNOTATION_FONT_COMPRESSED
          : teaching
            ? TIMELINE_ANNOTATION_FONT_SIZE
            : 13;
    const fillBg =
      phase === "active"
        ? "rgba(255, 255, 255, 0.97)"
        : phase === "passive"
          ? "rgba(248, 250, 252, 0.94)"
          : "rgba(241, 245, 249, 0.88)";
    const strokeColor =
      phase === "active" ? "#e2e8f0" : phase === "passive" ? "#e2e8f0" : "#cbd5e1";
    if (instructionLifecycleDebugEnabled()) {
      logEntityRender(projection, { x: box.x, y: box.y, w: box.w, h }, { opacity: groupOpacity, painted: true });
    }

    const keywordTitle = (() => {
      const targetId = projection.target_id;
      if (!targetId) return undefined;
      const owner = opts.bySourceEntityId[targetId];
      if (!owner || owner.projection_kind !== "node") return undefined;
      return owner.row_detail?.trim() || owner.label?.trim() || undefined;
    })();

    if (isCycleAnn && projection.target_id) {
      const ownerProj = opts.bySourceEntityId[projection.target_id];
      const ownerNodeBox =
        ownerProj?.projection_kind === "node"
          ? nodeBox(ownerProj, opts.layoutKind)
          : null;
      if (ownerNodeBox) {
        const { cx, cy } = cycleRingCenter(opts.viewport.width, opts.viewport.height);
        const placement =
          cycleCloudPlacementFromProjection(projection) ??
          resolveCycleCloudPlacement(
            ownerNodeBox.x + ownerNodeBox.w / 2,
            ownerNodeBox.y + ownerNodeBox.h / 2,
            { cx, cy },
          );
        return (
          <g
            key={projection.projection_id}
            className={teaching && enter && phase === "active" ? "v3-annotation-enter" : undefined}
          >
            <CycleCloudCallout
              projectionId={projection.projection_id}
              box={box}
              height={h}
              layoutLines={layoutLines}
              visibleLines={lines}
              fontSize={fontSize}
              lineHeight={lineHeight}
              opacity={groupOpacity}
              placement={placement}
              nodeBox={ownerNodeBox}
              phase={phase}
              teaching={teaching}
              speechPhase={speech.phase}
              keywordTitle={keywordTitle}
            />
          </g>
        );
      }
    }

    return (
      <g
        key={projection.projection_id}
        className={teaching && enter && phase === "active" ? "v3-annotation-enter" : undefined}
        opacity={groupOpacity}
      >
        <title>{projection.text}</title>
        <rect
          x={box.x}
          y={box.y}
          width={box.w}
          height={h}
          rx={teaching ? 10 : 8}
          fill={fillBg}
          stroke={strokeColor}
          strokeWidth={phase === "active" ? 1 : 0.85}
          filter={phase === "active" && teaching ? "url(#v3-card-shadow)" : undefined}
        />
        <TeachingExplanationText
          idPrefix={projection.projection_id}
          layoutLines={layoutLines}
          visibleLines={lines}
          originX={box.x + pad}
          originY={box.y + pad}
          lineHeight={lineHeight}
          fontSize={fontSize}
          speechPhase={isHistoryPhase ? "stable" : speech.phase}
          keywordTitle={keywordTitle}
          fontStyle={phase === "transient" ? "italic" : undefined}
          fill={phase === "transient" ? "#64748b" : "#1e293b"}
          teaching={teaching && !isHistoryPhase}
        />
      </g>
    );
  }

  if (projection.projection_kind === "label") {
    const speech = resolveSpeechDisplayText(
      projection.text,
      opts.speechRevealByEntityId?.[projection.source_entity_id],
      Boolean(opts.speechRevealEnabled && teaching),
    );
    const labelText = speech.visibleText || (speech.phase === "pending" ? "" : projection.text);
    if (!labelText && speech.phase === "pending") return null;
    return (
      <text
        key={projection.projection_id}
        x={box.x}
        y={box.y}
        fontSize={TIMELINE_LABEL_FONT_SIZE}
        fill="#334155"
        className="select-none"
        opacity={speech.phase === "speaking" ? 0.92 : 1}
      >
        {labelText}
      </text>
    );
  }

  return null;
}

export function MinimalDeterministicRenderer({
  projectionsByLayer,
  width = 960,
  height = 1040,
  debug = false,
  showDebugFallback = false,
  prodBaseline = false,
  layoutKind = "flow_left_right",
  presentation = "teaching",
  clipToViewport = false,
  stepKey = null,
  focusEntityId = null,
  ttlExpiredHighlightIds,
  speechRevealByEntityId,
  speechRevealEnabled = false,
}: {
  projectionsByLayer: Record<string, RenderProjection[]>;
  width?: number;
  height?: number;
  debug?: boolean;
  showDebugFallback?: boolean;
  prodBaseline?: boolean;
  layoutKind?: InstructionalLayoutKind;
  presentation?: "teaching" | "debug";
  /** When true, clip diagram ink to the viewBox (whiteboard surface). */
  clipToViewport?: boolean;
  /** When set (e.g. current operation id), drives entrance detection for teaching motion. */
  stepKey?: string | null;
  /** Entity id from current teaching step — emphasizes that node and dims others slightly. */
  focusEntityId?: string | null;
  /** Highlight entity ids whose ttl_ms elapsed during presentation (overlay hidden, nodes kept). */
  ttlExpiredHighlightIds?: ReadonlySet<string>;
  speechRevealByEntityId?: Readonly<Record<string, SpeechRevealState>>;
  speechRevealEnabled?: boolean;
}) {
  const showDebugChrome = debug && presentation === "debug";
  const renderTrace = showDebugChrome && process.env.NEXT_PUBLIC_V3_RENDER_TRACE === "1";
  const renderTestRectOnly = showDebugChrome && process.env.NEXT_PUBLIC_V3_RENDER_TEST_RECT === "1";

  const laidOutByLayer = useMemo(
    () => applyLayoutToLayers(projectionsByLayer, width, height, layoutKind),
    [projectionsByLayer, width, height, layoutKind],
  );

  const svgRef = useRef<SVGSVGElement | null>(null);
  const allProjections = RENDER_LAYER_ORDER.flatMap((layer) => laidOutByLayer[layer] ?? []);
  const debugFlatProjections = useMemo(
    () => [...allProjections].sort((a, b) => a.projection_id.localeCompare(b.projection_id)),
    [allProjections],
  );
  const bySourceEntityId: ProjectionMap = Object.fromEntries(
    allProjections.map((projection) => [projection.source_entity_id, projection]),
  );

  const rootEntityId = useMemo(() => {
    if (layoutKind !== "hierarchy_root_children") return null;
    const ids = allProjections
      .filter((p): p is Extract<RenderProjection, { projection_kind: "node" }> => p.projection_kind === "node")
      .map((p) => p.source_entity_id)
      .sort((a, b) => {
        const ma = a.match(/^node_(\d+)$/);
        const mb = b.match(/^node_(\d+)$/);
        if (ma && mb) return Number(ma[1]) - Number(mb[1]);
        return a.localeCompare(b);
      });
    return ids[0] ?? null;
  }, [allProjections, layoutKind]);

  const prevVisibleRef = useRef<Set<string>>(new Set());
  const [enterAnimIds, setEnterAnimIds] = useState<Set<string>>(() => new Set());
  const useEnterMotion = presentation === "teaching" && !clipToViewport;

  useLayoutEffect(() => {
    const now = new Set(allProjections.filter((p) => p.visible).map((p) => p.projection_id));
    const newly = new Set<string>();
    for (const id of now) {
      if (!prevVisibleRef.current.has(id)) newly.add(id);
    }
    prevVisibleRef.current = now;

    setEnterAnimIds((prev) => {
      if (!useEnterMotion) {
        return prev.size === 0 ? prev : new Set<string>();
      }
      if (newly.size > 4) {
        return prev.size === 0 ? prev : new Set<string>();
      }
      if (setsEqual(prev, newly)) return prev;
      return newly;
    });
  }, [allProjections, useEnterMotion, stepKey]);

  useEffect(() => {
    logProjectionState(allProjections, { layout_kind: layoutKind, step_key: stepKey ?? null });
    logVisibleRender(allProjections);
  }, [allProjections, layoutKind, stepKey]);

  const renderedCounts = {
    nodes: allProjections.filter((p) => p.projection_kind === "node").length,
    edges: allProjections.filter((p) => p.projection_kind === "edge").length,
    annotations: allProjections.filter((p) => p.projection_kind === "annotation").length,
    highlights: allProjections.filter((p) => p.projection_kind === "highlight").length,
  };

  const placementInk = useMemo(() => {
    const visible = projectionsForBoardFit(allProjections, layoutKind);
    const ctx: FitBoxContext = { bySourceEntityId, presentation, layoutKind };
    return laidOutInkBounds(
      visible,
      ctx,
      bySourceEntityId,
      rootEntityId,
      { width, height },
      layoutKind === "flow_vertical_process",
    );
  }, [allProjections, bySourceEntityId, height, layoutKind, presentation, rootEntityId, width]);

  const fitTransform = useMemo(() => {
    let bounds = placementInk;
    if (!bounds) return null;
    if (layoutKind === "comparison_split") {
      bounds = mergeContentBounds(bounds, comparisonSplitStageBounds(width, height, true));
    }
    if (layoutKind === "flow_vertical_process") {
      bounds = extendProcessStoryboardFitBounds(bounds);
    }
    const fitPad =
      layoutKind === "flow_vertical_process"
        ? PROCESS_BOARD_FIT_PADDING
        : layoutKind === "hierarchy_root_children"
          ? HIERARCHY_BOARD_FIT_PADDING
          : BOARD_FIT_PADDING;
    const fitAlign =
      layoutKind === "flow_vertical_process" || layoutKind === "hierarchy_root_children"
        ? "top"
        : "center";
    const fitUpscale = layoutKind === "flow_vertical_process" ? 1 : undefined;
    return computeBoardFitTransformFromBounds(bounds, width, height, fitPad, fitAlign, fitUpscale);
  }, [placementInk, width, height, layoutKind]);

  const effectiveFitTransform =
    fitTransform ??
    (allProjections.some((p) => p.visible)
      ? `translate(${BOARD_FIT_PADDING.left},${BOARD_FIT_PADDING.top}) scale(1)`
      : null);

  useEffect(() => {
    const visible = projectionsForBoardFit(allProjections, layoutKind);
    const ctx: FitBoxContext = { bySourceEntityId, presentation, layoutKind };
    const forFit = visible.map((p) => ({
      ...p,
      viewport_box: effectiveViewportBoxForFit(p, ctx),
    }));
    let bounds = contentBoundsFromProjections(forFit);
    for (const p of visible) {
      if (p.projection_kind !== "edge") continue;
      bounds = mergeContentBounds(
        bounds,
        edgeInkBounds(p, bySourceEntityId, layoutKind, rootEntityId, { width, height }),
      );
    }
    const parsed = parseBoardFitTransform(effectiveFitTransform);
    if (!bounds || !parsed) return;
    logBoardFit({
      content_bounds: {
        minX: bounds.minX,
        minY: bounds.minY,
        maxX: bounds.maxX,
        maxY: bounds.maxY,
      },
      viewport_bounds: { width, height },
      scale: parsed.scale,
      translate: parsed.translate,
      layout_mode: layoutKind,
      projection_count: visible.length,
    });
  }, [
    allProjections,
    bySourceEntityId,
    effectiveFitTransform,
    fitTransform,
    layoutKind,
    presentation,
    rootEntityId,
    width,
    height,
  ]);

  useEffect(() => {
    const parsed = parseBoardFitTransform(effectiveFitTransform);
    logSvgRender({
      viewBox: `0 0 ${width} ${height}`,
      scale: parsed?.scale ?? null,
      translate: parsed?.translate ?? null,
      svg_bounds: { width, height },
    });
  }, [effectiveFitTransform, height, width]);

  if (renderTrace) {
    // eslint-disable-next-line no-console
    console.log("[V3_DEBUG] MinimalDeterministicRenderer render begin", {
      prodBaseline,
      debug,
      layoutKind,
      presentation,
      projectionTotal: allProjections.length,
      layerKeys: RENDER_LAYER_ORDER.map((layer) => [
        layer,
        (laidOutByLayer[layer] ?? []).length,
      ]),
      renderTestRectOnly,
    });
  }

  useEffect(() => {
    if (!showDebugChrome || !svgRef.current) return;
    const svg = svgRef.current;
    const rect = svg.getBoundingClientRect();
    const styles = window.getComputedStyle(svg);
    // eslint-disable-next-line no-console
    console.info(
      "[V3_DEBUG] svg_dom_state",
      JSON.stringify({
        width_attr: svg.getAttribute("width"),
        height_attr: svg.getAttribute("height"),
        bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        projection_count: allProjections.length,
        rendered_count:
          renderedCounts.nodes +
          renderedCounts.edges +
          renderedCounts.annotations +
          renderedCounts.highlights,
        css: {
          visibility: styles.visibility,
          opacity: styles.opacity,
          zIndex: styles.zIndex,
          overflow: styles.overflow,
          transform: styles.transform,
          display: styles.display,
        },
      }),
    );
    // eslint-disable-next-line no-console
    console.info(
      "[V3_DEBUG] projection_coordinate_dump",
      allProjections.map((p) => ({
        id: p.projection_id,
        type: p.projection_kind,
        layer: p.layer,
        visible: p.visible,
        box: p.viewport_box,
      })),
    );
  }, [allProjections, showDebugChrome, renderedCounts.annotations, renderedCounts.edges, renderedCounts.highlights, renderedCounts.nodes]);

  if (renderTestRectOnly) {
    return (
      <div style={{ background: "yellow", padding: 12, fontWeight: 800 }}>
        RENDER TEST (NEXT_PUBLIC_V3_RENDER_TEST_RECT=1) — if you see this, the component mounts and
        this return path runs.
      </div>
    );
  }

  const teaching = presentation === "teaching";
  const comparisonRowMode = useMemo(
    () => shouldUseComparisonRowRenderer(layoutKind, presentation, allProjections),
    [layoutKind, presentation, allProjections],
  );
  const comparisonRowModel = useMemo(() => {
    if (!comparisonRowMode) return null;
    return buildComparisonRowUnits(allProjections, focusEntityId ?? null);
  }, [comparisonRowMode, allProjections, focusEntityId]);
  const comparisonRowNodeIds = useMemo(() => {
    if (!comparisonRowModel) return new Set<string>();
    const ids = new Set<string>();
    for (const unit of comparisonRowModel.units) {
      if (unit.left) ids.add(unit.left.entityId);
      if (unit.right) ids.add(unit.right.entityId);
    }
    return ids;
  }, [comparisonRowModel]);

  const displayLayout = useMemo(() => {
    let bounds = placementInk;
    if (comparisonRowModel) {
      for (const unit of reflowComparisonRowUnits(comparisonRowModel.units)) {
        if (unit.phase === "hidden" || unit.rowBox.h <= 0) continue;
        bounds = mergeContentBounds(bounds, {
          minX: unit.rowBox.x,
          minY: unit.rowBox.y,
          maxX: unit.rowBox.x + unit.rowBox.w,
          maxY: unit.rowBox.y + unit.rowBox.h,
        });
      }
    }
    const nodes = allProjections.filter(
      (p): p is Extract<RenderProjection, { projection_kind: "node" }> => p.projection_kind === "node",
    );
    const divider =
      bounds && layoutKind === "comparison_split"
        ? comparisonDividerForNodes(width, nodes, bounds.maxY, BOARD_DISPLAY_PAD)
        : null;
    if (bounds && divider) {
      bounds = mergeContentBounds(bounds, {
        minX: Math.min(bounds.minX, divider.centerX),
        minY: Math.min(bounds.minY, divider.topY),
        maxX: Math.max(bounds.maxX, divider.centerX),
        maxY: Math.max(bounds.maxY, divider.bottomY),
      });
    }
    return { bounds, divider };
  }, [allProjections, comparisonRowModel, layoutKind, placementInk, width]);

  const displayFrame = useMemo(() => {
    const parsed = parseBoardFitTransform(effectiveFitTransform);
    if (!displayLayout.bounds || !parsed) {
      return boardDisplayFrame({
        width,
        ink: { minX: 0, minY: 0, maxX: width, maxY: height },
        fit: { scale: 1, translate: { tx: 0, ty: 0 } },
        pad: 0,
      });
    }
    return boardDisplayFrame({ width, ink: displayLayout.bounds, fit: parsed });
  }, [displayLayout.bounds, effectiveFitTransform, height, width]);

  useEffect(() => {
    if (!comparisonRowMode || !comparisonRowModel || !instructionLifecycleDebugEnabled()) return;
    // eslint-disable-next-line no-console
    console.info("[COMPARISON_ROW_RENDER]", comparisonRowModel.stats);
  }, [comparisonRowMode, comparisonRowModel]);

  const sceneBg = teaching
    ? "linear-gradient(165deg, #faf9f6 0%, #f4f2eb 48%, #eef1f6 100%)"
    : "linear-gradient(180deg, #f8fafc 0%, #e0e7ff 55%, #eef2ff 100%)";

  const edgeObstacles = useMemo(
    () => clusterObstaclesFromProjections(allProjections),
    [allProjections],
  );

  const processNodeIds = useMemo(() => {
    if (layoutKind !== "flow_vertical_process") return [] as string[];
    return processNodeIdsFromProjections(allProjections);
  }, [layoutKind, allProjections]);

  const renderOpts: RenderOpts = {
    bySourceEntityId,
    layoutKind,
    rootEntityId,
    edgeObstacles,
    viewport: { width, height },
    showDebugChrome,
    presentation,
    enterAnimIds: useEnterMotion ? enterAnimIds : new Set(),
    useEnterMotion,
    focusEntityId: teaching ? focusEntityId ?? null : null,
    ttlExpiredHighlightIds,
    speechRevealByEntityId,
    speechRevealEnabled,
    processNodeIds,
  };
  const comparisonChrome = teaching ? displayLayout.divider : null;

  return (
    <svg
      ref={svgRef}
      width={width}
      height={displayFrame.frameH}
      viewBox={displayFrame.viewBox}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Instructional scene"
      className={`v3-minimal-deterministic-renderer ${TIMELINE_SVG_TEXT_CLASS}`}
      style={{
        background: sceneBg,
        overflow: "hidden",
        display: "block",
        width: "100%",
        maxWidth: "100%",
        height: clipToViewport ? "100%" : "auto",
        minHeight: clipToViewport ? 320 : undefined,
        maxHeight: clipToViewport ? "100%" : undefined,
        aspectRatio: clipToViewport ? undefined : `${width} / ${displayFrame.frameH}`,
      }}
    >
      <style>{TIMELINE_SVG_TEXT_CSS}</style>
      {teaching ? (
        <style>
          {`
            .v3-node-enter { animation: v3-node-in 0.48s ease-out both; }
            .v3-annotation-enter { animation: v3-ann-in 0.52s ease-out both; }
            .v3-highlight-enter { animation: v3-hi-in 0.4s ease-out both; }
            @keyframes v3-node-in {
              from { opacity: 0; transform: translateY(7px); }
              to { opacity: 1; transform: translateY(0); }
            }
            @keyframes v3-ann-in {
              from { opacity: 0; transform: translateY(5px); }
              to { opacity: 1; transform: translateY(0); }
            }
            @keyframes v3-hi-in {
              from { opacity: 0.35; }
              to { opacity: 1; }
            }
            .v3-word-fade-in {
              animation: v3-word-in 0.35s ease-out both;
            }
            @keyframes v3-word-in {
              from { opacity: 0.35; }
              to { opacity: 1; }
            }
            .v3-writing-marker {
              animation: v3-marker-write 0.55s ease-in-out infinite;
            }
            @keyframes v3-marker-write {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.88; }
            }
          `}
        </style>
      ) : null}

      <defs>
        <linearGradient id="v3-board-surface" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#f1f5f9" stopOpacity="0.15" />
        </linearGradient>
        <filter id="v3-soft-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.12" />
        </filter>
        <filter id="v3-node-shadow" x="-35%" y="-35%" width="170%" height="170%">
          <feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#0f172a" floodOpacity="0.07" />
        </filter>
        <filter id="v3-cloud-shadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#6366f1" floodOpacity="0.08" />
          <feDropShadow dx="0" dy="1" stdDeviation="2" floodOpacity="0.06" />
        </filter>
        <filter id="v3-card-shadow" x="-25%" y="-25%" width="150%" height="150%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.5" floodOpacity="0.08" />
        </filter>
        <filter id="v3-highlight-glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="v3-speech-active-glow" x="-20%" y="-30%" width="140%" height="160%">
          <feGaussianBlur stdDeviation="0.6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <marker
          id="v3-cycle-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
        </marker>
        <marker
          id="v3-flow-arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
        </marker>
        <clipPath id="v3-board-clip">
          <rect
            x={2}
            y={displayFrame.frameY + 2}
            width={width - 4}
            height={Math.max(0, displayFrame.frameH - 4)}
            rx={14}
          />
        </clipPath>
      </defs>

      {teaching ? (
        <rect
          x={0}
          y={displayFrame.frameY}
          width={width}
          height={displayFrame.frameH}
          fill="url(#v3-board-surface)"
          opacity={0.98}
        />
      ) : null}

      {prodBaseline && presentation === "debug" ? (
        <g data-v3-baseline="1" aria-hidden>
          <rect x={8} y={8} width={420} height={72} fill="#f97316" stroke="#9a3412" strokeWidth={4} rx={6} />
          <text x={20} y={52} fontSize={22} fontWeight={900} fill="#fff">
            V3 RENDERER ACTIVE (prod baseline)
          </text>
        </g>
      ) : null}

      {showDebugChrome ? (
        <>
          <rect x={20} y={20} width={280} height={140} fill="#ef4444" stroke="#7f1d1d" strokeWidth={6} />
          <circle cx={380} cy={90} r={58} fill="#22c55e" stroke="#14532d" strokeWidth={6} />
          <text x={24} y={48} fontSize={28} fontWeight={900} fill="#ffffff">
            SVG DEBUG ACTIVE
          </text>
        </>
      ) : null}

      {showDebugChrome ? (
        <>
          <rect x={1} y={1} width={width - 2} height={height - 2} fill="none" stroke="#64748b" strokeWidth={1.5} />
          {Array.from({ length: 11 }).map((_, i) => (
            <line
              key={`grid-x-${i}`}
              x1={(i * width) / 10}
              y1={0}
              x2={(i * width) / 10}
              y2={height}
              stroke="#cbd5e1"
              strokeWidth={0.6}
              opacity={0.6}
            />
          ))}
          {Array.from({ length: 7 }).map((_, i) => (
            <line
              key={`grid-y-${i}`}
              x1={0}
              y1={(i * height) / 6}
              x2={width}
              y2={(i * height) / 6}
              stroke="#cbd5e1"
              strokeWidth={0.6}
              opacity={0.6}
            />
          ))}
        </>
      ) : null}

      <g clipPath="url(#v3-board-clip)">
        <g transform={effectiveFitTransform ?? undefined}>
          {comparisonChrome
            ? ((divider) => {
                const { centerX, topY, bottomY } = divider;
                const vsY = topY + 28;
                return (
                  <g data-v3-comparison-chrome="1" aria-hidden pointerEvents="none">
                    <line
                      x1={centerX}
                      y1={topY}
                      x2={centerX}
                      y2={bottomY}
                      stroke="#cbd5e1"
                      strokeWidth={2}
                      strokeDasharray="6 5"
                      opacity={0.85}
                    />
                    <rect
                      x={centerX - 22}
                      y={vsY - 14}
                      width={44}
                      height={28}
                      rx={14}
                      fill="#f8fafc"
                      stroke="#94a3b8"
                      strokeWidth={1.25}
                      opacity={0.95}
                    />
                    <text
                      x={centerX}
                      y={vsY + 5}
                      textAnchor="middle"
                      fontSize={TIMELINE_LABEL_FONT_SIZE}
                      fontWeight={700}
                      fill="#64748b"
                      className="select-none"
                    >
                      vs
                    </text>
                  </g>
                );
              })(comparisonChrome)
            : null}
          {RENDER_LAYER_ORDER.map((layer) => {
            const entries = (laidOutByLayer[layer] ?? []).filter((projection) => {
              if (!comparisonRowMode) return true;
              if (isComparisonRowAlignedProjection(projection, comparisonRowNodeIds)) return false;
              if (projection.projection_kind === "annotation") {
                const text = projection.text.trim();
                if (/^Header:\s/i.test(text)) return false;
                if (/^On the (left|right):\s/i.test(text)) return false;
                const targetId = projection.target_id;
                if (targetId) {
                  const target = bySourceEntityId[targetId];
                  if (
                    target?.projection_kind === "node" &&
                    (target.teaching_hints?.comparison_tier === "header" ||
                      String(target.teaching_hints?.semantic_role ?? "")
                        .toLowerCase()
                        .includes("header"))
                  ) {
                    return false;
                  }
                }
              }
              return true;
            });
            return (
              <g key={layer} data-layer={layer}>
                {entries.map((projection) => renderProjection(projection, renderOpts))}
              </g>
            );
          })}
          {comparisonRowMode && comparisonRowModel ? (
            <ComparisonRowRendererView
              units={comparisonRowModel.units}
              opts={{
                enterAnimIds: useEnterMotion ? enterAnimIds : new Set(),
                useEnterMotion,
                speechRevealByEntityId,
                speechRevealEnabled,
              }}
            />
          ) : null}
          {showDebugChrome ? (
            <g data-layer="debug-flat-projections" pointerEvents="none">
              {debugFlatProjections.map((projection, idx) => {
                const c = debugClampedBox(projection.viewport_box);
                const hue = (idx * 47) % 360;
                return (
                  <g key={`flat:${projection.projection_id}`}>
                    <rect
                      x={c.x}
                      y={c.y}
                      width={c.w}
                      height={c.h}
                      fill={`hsla(${hue} 90% 60% / 0.25)`}
                      stroke={`hsl(${hue} 90% 35%)`}
                      strokeWidth={6}
                    />
                    <text x={c.x + 8} y={c.y + 30} fontSize={22} fontWeight={900} fill="#111827">
                      {projection.projection_kind.toUpperCase()}
                    </text>
                  </g>
                );
              })}
            </g>
          ) : null}
        </g>
      </g>

      {showDebugChrome ? (
        <>
          <text x={8} y={height - 24} fontSize="10" fill="#0f172a">
            projection-render-debug
          </text>
          <text x={8} y={height - 10} fontSize="10" fill="#0f172a">
            rendered nodes:{renderedCounts.nodes} edges:{renderedCounts.edges} annotations:{renderedCounts.annotations}{" "}
            highlights:{renderedCounts.highlights}
          </text>
        </>
      ) : null}

      {showDebugChrome && showDebugFallback
        ? allProjections.map((projection) => {
            const b = projection.viewport_box;
            return (
              <g key={`fallback:${projection.projection_id}`}>
                <rect
                  x={b.x}
                  y={b.y}
                  width={Math.max(b.w, 8)}
                  height={Math.max(b.h, 8)}
                  fill="none"
                  stroke="#ef4444"
                  strokeDasharray="3 2"
                  opacity={0.8}
                />
              </g>
            );
          })
        : null}
    </svg>
  );
}
