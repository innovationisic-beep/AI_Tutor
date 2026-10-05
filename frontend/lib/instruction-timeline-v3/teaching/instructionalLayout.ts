import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { RENDER_LAYER_ORDER } from "@/lib/instruction-timeline-v3/renderer/renderLayers";
import {
  COMPARISON_CENTER_X_RATIO,
  COMPARISON_DIVIDER_GAP,
  COMPARISON_HEADER_H,
  COMPARISON_HEADER_TO_ROWS_GAP,
  COMPARISON_HEADER_Y,
  COMPARISON_ROW_GAP,
  COMPARISON_ROW_H,
  COMPARISON_SIDE_PAD,
  comparisonDividerGeometry,
  extractComparisonHints,
  hintsFromNodeProjection,
  partitionComparisonNodes,
} from "@/lib/instruction-timeline-v3/teaching/comparisonSplit";
import type { InstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  layoutProcessStoryboardRows,
  type ProcessStoryboardRowLayout,
} from "@/lib/instruction-timeline-v3/teaching/processStoryboardLayout";
import {
  balanceSceneInViewport,
  buildCompositionContext,
  composeAnnotations,
  estimateAnnotationStackHeight,
} from "@/lib/instruction-timeline-v3/teaching/sceneComposition";

export {
  COMPARISON_CENTER_X_RATIO,
  COMPARISON_DIVIDER_GAP,
  comparisonDividerCenterX,
  comparisonDividerForNodes,
  comparisonDividerGeometry,
  comparisonSplitStageBounds,
  resolveComparisonDividerCenterX,
} from "@/lib/instruction-timeline-v3/teaching/comparisonSplit";

const NODE_MIN_W = 160;
const NODE_MIN_H = 68;
const ANNOTATION_PAD = 14;
const HIGHLIGHT_PAD = 12;
/** Vertical gap reserved for fork/trunk lines between root and child row (no annotation on root). */
const HIERARCHY_TRUNK_GAP = 36;
/**
 * Cycle ring center as a fraction of viewport height.
 * 0.32 positions the ring in the upper third, leaving the lower two-thirds for annotation cards.
 */
export const CYCLE_RING_CY_RATIO = 0.32;

/** Ellipse radius for n nodes on a cycle (aligned with backend ``_compute_cir_node_positions``). */
export function cycleRingRadius(n: number, width: number, height: number): number {
  const nn = Math.max(1, Math.min(8, n));
  // Keep ring compact enough that side-node annotation boxes (160 px wide) fit inside the viewport.
  // Side clearance needed: cx - r - nodeHalfW - annW - 24 >= 0
  // → r <= cx - nodeHalfW - 184  (annW 160 + 24 padding)
  // Using a fixed safe cap keeps the ring well within the canvas.
  return Math.min(Math.min(width, height) * 0.22, Math.min(200, 70 + nn * 24));
}

function cloneBox(p: RenderProjection, box: { x: number; y: number; w: number; h: number }): RenderProjection {
  return { ...p, viewport_box: { ...box } };
}

/** Sort entity ids like node_1, node_2, … numerically when possible. */
function sortNodeIds(ids: string[]): string[] {
  return [...ids].sort((a, b) => {
    const ma = a.match(/^node_(\d+)$/);
    const mb = b.match(/^node_(\d+)$/);
    if (ma && mb) return Number(ma[1]) - Number(mb[1]);
    return a.localeCompare(b);
  });
}

/**
 * Deterministic instructional geometry in viewport pixel space (matches SVG viewBox).
 */
export function applyInstructionalLayout(
  projections: RenderProjection[],
  width: number,
  height: number,
  kind: InstructionalLayoutKind,
): RenderProjection[] {
  const nodes = projections.filter((p): p is Extract<RenderProjection, { projection_kind: "node" }> => p.projection_kind === "node");
  const edges = projections.filter((p): p is Extract<RenderProjection, { projection_kind: "edge" }> => p.projection_kind === "edge");
  const annotations = projections.filter(
    (p): p is Extract<RenderProjection, { projection_kind: "annotation" }> => p.projection_kind === "annotation",
  );
  const highlights = projections.filter(
    (p): p is Extract<RenderProjection, { projection_kind: "highlight" }> => p.projection_kind === "highlight",
  );
  const rest = projections.filter(
    (p) =>
      p.projection_kind !== "node" &&
      p.projection_kind !== "edge" &&
      p.projection_kind !== "annotation" &&
      p.projection_kind !== "highlight",
  );

  const nodeIds = sortNodeIds(nodes.map((n) => n.source_entity_id));
  const byId = new Map(nodes.map((n) => [n.source_entity_id, n]));

  const boxes = new Map<string, { x: number; y: number; w: number; h: number }>();
  let processStoryboardRows: ProcessStoryboardRowLayout[] | null = null;

  if (kind === "hierarchy_root_children" && nodeIds.length >= 1) {
    const rootId = nodeIds[0];
    const childIds = nodeIds.slice(1);
    const rootW = Math.max(NODE_MIN_W + 48, 268);
    const rootH = Math.max(NODE_MIN_H + 24, 92);
    const rootX = width / 2 - rootW / 2;
    const rootY = 6;
    boxes.set(rootId, { x: rootX, y: rootY, w: rootW, h: rootH });

    // Root has no annotation — children start directly below with trunk gap only
    const rootBottom = rootY + rootH;
    const rowY = rootBottom + HIERARCHY_TRUNK_GAP;

    // Max 4 children per row; child width scales to fit 4 columns with gap
    const nChildren = childIds.length;
    if (nChildren > 0) {
      const maxPerRow = Math.min(4, nChildren);
      const gap = 32;
      // childW must fit maxPerRow nodes with gaps inside viewport width with side margins
      const availableW = width - 64;
      const childW = Math.min(
        Math.max(NODE_MIN_W + 20, 196),
        Math.floor((availableW - gap * (maxPerRow - 1)) / maxPerRow),
      );
      const childH = Math.max(NODE_MIN_H + 18, 84);
      // baseRowGap: extra vertical breathing room between rows (on top of annotation stack)
      const baseRowGap = 40;
      const rows = Math.ceil(nChildren / maxPerRow);
      let yCursor = rowY;
      for (let r = 0; r < rows; r += 1) {
        const slice = childIds.slice(r * maxPerRow, (r + 1) * maxPerRow);
        const totalW = slice.length * childW + (slice.length - 1) * gap;
        let x = width / 2 - totalW / 2;
        const y = yCursor;
        let rowStack = 0;
        for (const cid of slice) {
          boxes.set(cid, { x, y, w: childW, h: childH });
          // Annotation heights use worst-case char estimates, so no extra multiplier needed
          const estimated = estimateAnnotationStackHeight(annotations, cid, width, kind, {
            x,
            y,
            w: childW,
            h: childH,
          });
          rowStack = Math.max(rowStack, estimated);
          x += childW + gap;
        }
        yCursor += childH + baseRowGap + rowStack;
      }
    }
  } else if (kind === "flow_vertical_process" && nodeIds.length >= 1) {
    processStoryboardRows = layoutProcessStoryboardRows(
      nodeIds,
      annotations.map((a) => ({
        target_id: a.target_id,
        text: a.text,
        annotation_phase: a.annotation_phase,
      })),
      width,
      byId as Map<string, Extract<RenderProjection, { projection_kind: "node" }>>,
    );
    for (const row of processStoryboardRows) {
      boxes.set(row.nodeId, row.nodeBox);
    }
  } else if (kind === "grouped_cluster" && nodeIds.length >= 1) {
    const clusterGap = 40;
    const innerGap = 28;
    const nodeW = Math.max(NODE_MIN_W, 200);
    const nodeH = Math.max(NODE_MIN_H, 78);
    const perRow = Math.min(nodeIds.length, Math.max(2, Math.floor(Math.sqrt(nodeIds.length * 1.4))));
    const rows = Math.ceil(nodeIds.length / perRow);
    const rowOffsets: number[] = [];
    let accRowY = 0;
    for (let r = 0; r < rows; r += 1) {
      rowOffsets.push(accRowY);
      let maxStack = 0;
      for (let c = 0; c < perRow; c += 1) {
        const idx = r * perRow + c;
        if (idx >= nodeIds.length) break;
        maxStack = Math.max(
          maxStack,
          estimateAnnotationStackHeight(annotations, nodeIds[idx], width, kind, {
            x: 0,
            y: 0,
            w: nodeW,
            h: nodeH,
          }),
        );
      }
      accRowY += nodeH + innerGap + maxStack;
    }
    const gridW = perRow * nodeW + (perRow - 1) * innerGap;
    const gridH = accRowY > 0 ? accRowY - innerGap : nodeH;
    let startX = width / 2 - gridW / 2;
    let startY = height / 2 - gridH / 2;
    startX = Math.max(clusterGap, Math.min(startX, width - gridW - clusterGap));
    startY = Math.max(clusterGap, Math.min(startY, height - gridH - clusterGap));
    nodeIds.forEach((id, i) => {
      const col = i % perRow;
      const row = Math.floor(i / perRow);
      boxes.set(id, {
        x: startX + col * (nodeW + innerGap),
        y: startY + (rowOffsets[row] ?? 0),
        w: nodeW,
        h: nodeH,
      });
    });
  } else if (kind === "comparison_split" && nodeIds.length >= 1) {
    const partition = partitionComparisonNodes(nodeIds, (id) => {
      const nodeProj = byId.get(id);
      const hints = hintsFromNodeProjection(nodeProj);
      const idx = nodeIds.indexOf(id);
      return extractComparisonHints(id, hints, idx, nodeIds.length, hints?.semantic_role);
    });

    const hasHeaderRow = Boolean(partition.leftHeader || partition.rightHeader);
    const centerX = width * COMPARISON_CENTER_X_RATIO;
    const halfGap = COMPARISON_DIVIDER_GAP / 2;
    const leftColW = Math.max(
      NODE_MIN_W,
      Math.floor(centerX - halfGap - COMPARISON_SIDE_PAD) - COMPARISON_SIDE_PAD,
    );
    const rightColW = Math.max(
      NODE_MIN_W,
      Math.floor(width - centerX - halfGap - COMPARISON_SIDE_PAD) - COMPARISON_SIDE_PAD,
    );
    const leftX = COMPARISON_SIDE_PAD;
    const rightX = Math.round(centerX + halfGap);
    const headerH = Math.max(NODE_MIN_H, COMPARISON_HEADER_H);
    const rowH = Math.max(NODE_MIN_H, COMPARISON_ROW_H);
    let rowY = hasHeaderRow
      ? COMPARISON_HEADER_Y + headerH + COMPARISON_HEADER_TO_ROWS_GAP
      : COMPARISON_HEADER_Y + 24;

    const place = (id: string, side: "left" | "right", y: number, isHeader: boolean) => {
      const w = side === "left" ? leftColW : rightColW;
      const h = isHeader ? headerH : rowH;
      const x = side === "left" ? leftX : rightX;
      boxes.set(id, { x, y, w, h });
    };

    if (partition.leftHeader) {
      place(partition.leftHeader, "left", COMPARISON_HEADER_Y, true);
    }
    if (partition.rightHeader) {
      place(partition.rightHeader, "right", COMPARISON_HEADER_Y, true);
    }

    for (const row of partition.rows) {
      if (row.left) place(row.left, "left", rowY, false);
      if (row.right) place(row.right, "right", rowY, false);
      rowY += rowH + COMPARISON_ROW_GAP;
    }
  } else if (kind === "cycle_ring" && nodeIds.length >= 1) {
    const n = Math.min(8, Math.max(1, nodeIds.length));
    const cx = width / 2;
    const cy = height * CYCLE_RING_CY_RATIO;
    const r = cycleRingRadius(n, width, height);
    const nodeW = Math.max(NODE_MIN_W, Math.min(220, 248 - n * 8));
    const nodeH = Math.max(NODE_MIN_H, Math.min(88, 92 - n * 2));
    nodeIds.forEach((id, i) => {
      const theta = -Math.PI / 2 + (2 * Math.PI * i) / n;
      const ncx = cx + r * Math.cos(theta);
      const ncy = cy + r * Math.sin(theta);
      boxes.set(id, {
        x: Math.round(ncx - nodeW / 2),
        y: Math.round(ncy - nodeH / 2),
        w: nodeW,
        h: nodeH,
      });
    });
  } else {
    /* flow_left_right */
    const gap = 36;
    const nodeW = Math.max(NODE_MIN_W, Math.min(200, (width - gap * (nodeIds.length + 1)) / Math.max(1, nodeIds.length)));
    const nodeH = Math.max(NODE_MIN_H, 74);
    let x = 48;
    const y = height / 2 - nodeH / 2;
    for (const id of nodeIds) {
      boxes.set(id, { x, y, w: nodeW, h: nodeH });
      x += nodeW + gap;
    }
  }

  const laidOutNodes = nodes.map((n) => {
    const b = boxes.get(n.source_entity_id) ?? n.viewport_box;
    return cloneBox(n, {
      x: b.x,
      y: b.y,
      w: Math.max(NODE_MIN_W, b.w),
      h: Math.max(NODE_MIN_H, b.h),
    });
  });

  const nodeBoxMap = new Map(laidOutNodes.map((n) => [n.source_entity_id, n.viewport_box]));

  const compositionCtx = buildCompositionContext(kind, width, height, nodeIds, nodeBoxMap);
  let laidOutAnnotations = composeAnnotations(annotations, compositionCtx);
  if (kind === "flow_vertical_process" && processStoryboardRows) {
    const explByTarget = new Map(
      processStoryboardRows
        .filter((r) => r.explanationBox)
        .map((r) => [r.nodeId, r.explanationBox!] as const),
    );
    laidOutAnnotations = laidOutAnnotations.map((ann) => {
      if (!ann.target_id) return ann;
      const expl = explByTarget.get(ann.target_id);
      if (!expl) return ann;
      return cloneBox(ann, expl);
    });
  }

  const laidOutHighlights = highlights.map((h) => {
    const rect = { x: 0, y: 0, w: 40, h: 40 };
    for (const tid of h.target_ids) {
      const b = nodeBoxMap.get(tid);
      if (!b) continue;
      if (rect.w < 20) {
        rect.x = b.x - HIGHLIGHT_PAD;
        rect.y = b.y - HIGHLIGHT_PAD;
        rect.w = b.w + HIGHLIGHT_PAD * 2;
        rect.h = b.h + HIGHLIGHT_PAD * 2;
      } else {
        const nx = Math.min(rect.x, b.x - HIGHLIGHT_PAD);
        const ny = Math.min(rect.y, b.y - HIGHLIGHT_PAD);
        const rx = Math.max(rect.x + rect.w, b.x + b.w + HIGHLIGHT_PAD);
        const by = Math.max(rect.y + rect.h, b.y + b.h + HIGHLIGHT_PAD);
        rect.x = nx;
        rect.y = ny;
        rect.w = rx - nx;
        rect.h = by - ny;
      }
    }
    if (rect.w < 30 && h.target_ids[0]) {
      const b = nodeBoxMap.get(h.target_ids[0]);
      if (b) {
        return cloneBox(h, {
          x: b.x - HIGHLIGHT_PAD,
          y: b.y - HIGHLIGHT_PAD,
          w: b.w + HIGHLIGHT_PAD * 2,
          h: b.h + HIGHLIGHT_PAD * 2,
        });
      }
    }
    return cloneBox(h, rect);
  });

  const laidOutEdges = edges.map((e) => cloneBox(e, e.viewport_box));

  const merged = [...laidOutNodes, ...laidOutEdges, ...laidOutAnnotations, ...laidOutHighlights, ...rest];
  return balanceSceneInViewport(merged, width, height, kind);
}

export function applyLayoutToLayers(
  byLayer: Record<string, RenderProjection[]>,
  width: number,
  height: number,
  kind: InstructionalLayoutKind,
): Record<string, RenderProjection[]> {
  const known = new Set<string>(RENDER_LAYER_ORDER);
  const flat = [
    ...RENDER_LAYER_ORDER.flatMap((layer) => byLayer[layer] ?? []),
    ...Object.keys(byLayer)
      .filter((layer) => !known.has(layer))
      .flatMap((layer) => byLayer[layer] ?? []),
  ];
  const laidOut = applyInstructionalLayout(flat, width, height, kind);
  const next: Record<string, RenderProjection[]> = {};
  for (const layer of RENDER_LAYER_ORDER) next[layer] = [];
  for (const p of laidOut) {
    next[p.layer] = next[p.layer] ?? [];
    next[p.layer].push(p);
  }
  return next;
}
