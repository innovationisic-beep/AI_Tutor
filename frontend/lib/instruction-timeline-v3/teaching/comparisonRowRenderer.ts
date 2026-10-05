import type {
  RenderAnnotationProjection,
  RenderNodeProjection,
  RenderProjection,
} from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import {
  COMPARISON_ROW_GAP,
  COMPARISON_ROW_H,
  extractComparisonHints,
  hintsFromNodeProjection,
  partitionComparisonNodes,
  type ComparisonSide,
} from "@/lib/instruction-timeline-v3/teaching/comparisonSplit";
import { wrapTeachingExplanationForRow } from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";
import {
  TIMELINE_COMPARISON_DIMENSION_RESERVE,
  TIMELINE_COMPARISON_FONT_SIZE,
  TIMELINE_COMPARISON_LINE_HEIGHT,
  timelineCharsPerLine,
} from "@/lib/teachingTypography";

export type ComparisonRowPhase = "hidden" | "active" | "passive";

export type ComparisonRowCell = {
  entityId: string;
  side: ComparisonSide;
  text: string;
  box: { x: number; y: number; w: number; h: number };
  visible: boolean;
};

export type ComparisonRowUnit = {
  pairIndex: number;
  dimension: string | null;
  left: ComparisonRowCell | null;
  right: ComparisonRowCell | null;
  rowBox: { x: number; y: number; w: number; h: number };
  phase: ComparisonRowPhase;
};

export type ComparisonRowRenderStats = {
  comparison_row_count: number;
  orphan_side_errors: number;
  invalid_side_assignments: number;
  comparison_render_mode: "row_aligned";
  detached_annotation_count: number;
  orphan_row_count: number;
  repaired_row_count: number;
  skipped_incomplete_rows: number;
  invalid_dimension_pairs: number;
};

function isComparisonRowNode(node: RenderNodeProjection): boolean {
  const tier = node.teaching_hints?.comparison_tier;
  const role = String(node.teaching_hints?.semantic_role ?? "").toLowerCase();
  if (tier === "header") return false;
  if (role.includes("header") || role === "column_header") return false;
  return tier === "row" || role.includes("comparison_row");
}

function rowDetailText(node: RenderNodeProjection, annotationText?: string): string {
  const detail = node.row_detail?.trim();
  if (detail) return detail;
  if (annotationText?.trim()) return annotationText.trim();
  return node.label.trim();
}

function isCompleteCellText(text: string): boolean {
  const t = text.trim();
  return t.length >= 3 && !/^\[?(?:detailed|todo|tbd|placeholder)/i.test(t);
}

function isSideLabelDimension(text: string, projections: RenderProjection[]): boolean {
  const headers = projections
    .filter((p): p is RenderNodeProjection => p.projection_kind === "node")
    .filter((n) => {
      const role = String(n.teaching_hints?.semantic_role ?? "").toLowerCase();
      return role.includes("header") || n.teaching_hints?.comparison_tier === "header";
    })
    .map((n) => n.label.trim().toLowerCase())
    .filter(Boolean);
  const head = text.trim().toLowerCase();
  return headers.some((h) => h === head || head.startsWith(`${h}:`));
}

function dimensionFromText(text: string, projections: RenderProjection[]): string | null {
  const trimmed = text.trim();
  if (!trimmed.includes(":")) return null;
  const head = trimmed.split(":", 1)[0]?.trim() ?? "";
  if (head && head.split(/\s+/).length <= 4 && !isSideLabelDimension(head, projections)) return head;
  return null;
}

function emptyRowCell(side: ComparisonSide): ComparisonRowCell {
  return {
    entityId: "",
    side,
    text: "",
    box: { x: 0, y: 0, w: 0, h: 0 },
    visible: false,
  };
}

function rowBoxFromCells(left: ComparisonRowCell | null, right: ComparisonRowCell | null) {
  if (left && right) return mergeRowBox(left, right);
  if (left) return { ...left.box };
  if (right) return { ...right.box };
  return { x: 0, y: 0, w: 0, h: 0 };
}

function mergeRowBox(left: ComparisonRowCell, right: ComparisonRowCell) {
  const cells = [left, right];
  const xs = cells.map((c) => c.box.x);
  const ys = cells.map((c) => c.box.y);
  const x2 = cells.map((c) => c.box.x + c.box.w);
  const y2 = cells.map((c) => c.box.y + c.box.h);
  return {
    x: Math.min(...xs),
    y: Math.min(...ys),
    w: Math.max(...x2) - Math.min(...xs),
    h: Math.max(...y2) - Math.min(...ys),
  };
}

function resolveRowPhase(
  pairIndex: number,
  left: ComparisonRowCell,
  right: ComparisonRowCell,
  focusEntityId: string | null,
  activePairIndex: number | null,
): ComparisonRowPhase {
  if (!left.visible && !right.visible) return "hidden";

  const bothVisible = left.visible && right.visible;
  if (!bothVisible) {
    if (focusEntityId && (left.entityId === focusEntityId || right.entityId === focusEntityId)) {
      return "active";
    }
    if (left.visible && !right.visible) return "active";
    if (right.visible && !left.visible) return "active";
    return "passive";
  }

  if (focusEntityId && (left.entityId === focusEntityId || right.entityId === focusEntityId)) {
    return "active";
  }
  if (activePairIndex != null && pairIndex === activePairIndex) return "active";
  if (activePairIndex != null && pairIndex < activePairIndex) return "passive";
  return "passive";
}

export function activeComparisonPairIndex(
  nodes: RenderNodeProjection[],
  focusEntityId: string | null,
): number | null {
  if (!focusEntityId) return null;
  for (const node of nodes) {
    if (node.source_entity_id !== focusEntityId) continue;
    if (typeof node.teaching_hints?.pair_index === "number") return node.teaching_hints.pair_index;
  }
  return null;
}

type RowPairSlot = { pairIndex: number; leftId?: string; rightId?: string };

function pairRowsByIndex(rowNodes: RenderNodeProjection[]): {
  pairs: RowPairSlot[];
  invalidSide: number;
} {
  const byPair = new Map<number, { left?: string; right?: string }>();
  let invalidSide = 0;

  for (const node of rowNodes) {
    const hints = node.teaching_hints;
    const pairIndex = hints?.pair_index;
    const side = hints?.comparison_side;
    if (typeof pairIndex !== "number" || pairIndex < 0 || !side) continue;
    const slot = byPair.get(pairIndex) ?? {};
    if (side === "left") {
      if (slot.left && slot.left !== node.source_entity_id) invalidSide += 1;
      slot.left = node.source_entity_id;
    } else {
      if (slot.right && slot.right !== node.source_entity_id) invalidSide += 1;
      slot.right = node.source_entity_id;
    }
    byPair.set(pairIndex, slot);
  }

  const pairs: RowPairSlot[] = [];
  for (const [pairIndex, slot] of [...byPair.entries()].sort((a, b) => a[0] - b[0])) {
    pairs.push({ pairIndex, leftId: slot.left, rightId: slot.right });
  }
  return { pairs, invalidSide };
}

function buildCell(
  entityId: string,
  side: ComparisonSide,
  node: RenderNodeProjection,
  annByTarget: Map<string, string>,
): ComparisonRowCell {
  return {
    entityId,
    side,
    text: rowDetailText(node, annByTarget.get(entityId)),
    box: node.viewport_box,
    visible: node.visible,
  };
}

export function buildComparisonRowUnits(
  projections: RenderProjection[],
  focusEntityId: string | null,
): { units: ComparisonRowUnit[]; stats: ComparisonRowRenderStats } {
  const nodes = projections.filter((p): p is RenderNodeProjection => p.projection_kind === "node");
  const rowNodes = nodes.filter(isComparisonRowNode);
  const nodeById = new Map(rowNodes.map((n) => [n.source_entity_id, n]));
  const annotations = projections.filter(
    (p): p is RenderAnnotationProjection => p.projection_kind === "annotation",
  );
  const annByTarget = new Map<string, string>();
  for (const ann of annotations) {
    if (ann.target_id) annByTarget.set(ann.target_id, ann.text);
  }

  const { pairs: indexedPairs, invalidSide: indexInvalid } = pairRowsByIndex(rowNodes);
  let orphanSide = 0;
  let skippedIncomplete = 0;
  let invalidDimension = 0;

  const pairSlots: RowPairSlot[] =
    indexedPairs.length > 0
      ? indexedPairs
      : (() => {
          const nodeIds = rowNodes.map((n) => n.source_entity_id);
          const hintFor = (id: string) => {
            const node = nodeById.get(id);
            const hints = hintsFromNodeProjection(node);
            const idx = nodeIds.indexOf(id);
            return extractComparisonHints(
              id,
              hints,
              idx,
              nodeIds.length,
              hints?.semantic_role,
            );
          };
          const partition = partitionComparisonNodes(nodeIds, hintFor);
          for (const row of partition.rows) {
            if (row.left && !row.right) orphanSide += 1;
            if (row.right && !row.left) orphanSide += 1;
          }
          return partition.rows.map((row, pairIndex) => ({
            pairIndex,
            leftId: row.left ?? undefined,
            rightId: row.right ?? undefined,
          }));
        })();

  const activePair = activeComparisonPairIndex(rowNodes, focusEntityId);
  const units: ComparisonRowUnit[] = [];

  for (const slot of pairSlots) {
    if (!slot.leftId && !slot.rightId) {
      skippedIncomplete += 1;
      continue;
    }

    const leftNode = slot.leftId ? nodeById.get(slot.leftId) : undefined;
    const rightNode = slot.rightId ? nodeById.get(slot.rightId) : undefined;
    if (!leftNode && !rightNode) {
      skippedIncomplete += 1;
      continue;
    }

    const left = leftNode ? buildCell(slot.leftId!, "left", leftNode, annByTarget) : null;
    const right = rightNode ? buildCell(slot.rightId!, "right", rightNode, annByTarget) : null;

    if (left && !isCompleteCellText(left.text)) {
      skippedIncomplete += 1;
      continue;
    }
    if (right && !isCompleteCellText(right.text)) {
      if (!left) {
        skippedIncomplete += 1;
        continue;
      }
    }
    if (!left && !right) {
      skippedIncomplete += 1;
      continue;
    }

    const dimension =
      leftNode?.teaching_hints?.comparison_dimension ??
      rightNode?.teaching_hints?.comparison_dimension ??
      (left ? dimensionFromText(left.text, projections) : null) ??
      (right ? dimensionFromText(right.text, projections) : null) ??
      null;
    if (!dimension || !isCompleteCellText(dimension)) {
      invalidDimension += 1;
      skippedIncomplete += 1;
      continue;
    }

  if (!slot.leftId || !slot.rightId) {
      if (slot.leftId || slot.rightId) orphanSide += 1;
    }

    const phaseLeft = left ?? emptyRowCell("left");
    const phaseRight = right ?? emptyRowCell("right");

    units.push({
      pairIndex: slot.pairIndex,
      dimension,
      left,
      right,
      rowBox: rowBoxFromCells(left, right),
      phase: resolveRowPhase(slot.pairIndex, phaseLeft, phaseRight, focusEntityId, activePair),
    });
  }

  const rowNodeIds = new Set(rowNodes.map((n) => n.source_entity_id));
  const detachedForRows = annotations.filter(
    (ann) => ann.visible && ann.target_id && rowNodeIds.has(ann.target_id),
  ).length;

  return {
    units,
    stats: {
      comparison_row_count: units.length,
      orphan_side_errors: orphanSide,
      invalid_side_assignments: indexInvalid,
      comparison_render_mode: "row_aligned",
      detached_annotation_count: detachedForRows,
      orphan_row_count: orphanSide,
      repaired_row_count: 0,
      skipped_incomplete_rows: skippedIncomplete,
      invalid_dimension_pairs: invalidDimension,
    },
  };
}

export function shouldUseComparisonRowRenderer(
  layoutKind: string,
  presentation: string,
  projections: RenderProjection[],
): boolean {
  if (layoutKind !== "comparison_split" || presentation !== "teaching") return false;
  return projections.some(
    (p) => p.projection_kind === "node" && isComparisonRowNode(p as RenderNodeProjection),
  );
}

export function isComparisonRowAlignedProjection(
  projection: RenderProjection,
  rowNodeIds: ReadonlySet<string>,
): boolean {
  if (projection.projection_kind === "node" && rowNodeIds.has(projection.source_entity_id)) {
    return true;
  }
  if (
    projection.projection_kind === "annotation" &&
    projection.target_id &&
    rowNodeIds.has(projection.target_id)
  ) {
    return true;
  }
  return false;
}

export const COMPARISON_ROW_FONT_SIZE = TIMELINE_COMPARISON_FONT_SIZE;
export const COMPARISON_ROW_PAD = 14;
export const COMPARISON_ROW_LINE_HEIGHT = TIMELINE_COMPARISON_LINE_HEIGHT;
/** Minimum row card height; cells grow taller when prose needs more lines. */
export const COMPARISON_ROW_MIN_H = COMPARISON_ROW_H;
/** Soft cap — avoids runaway layout; full text still wraps within this. */
export const COMPARISON_ROW_LAYOUT_MAX_LINES = 14;

/** Max characters per line from cell inner width (SVG text has no auto-wrap). */
export function comparisonRowCharsPerLine(
  cellWidth: number,
  _fontSize = COMPARISON_ROW_FONT_SIZE,
  pad = COMPARISON_ROW_PAD,
): number {
  return timelineCharsPerLine(cellWidth, pad);
}

export function wrapComparisonRowText(text: string, maxCharsPerLine: number, maxLines: number): string[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];
  const cap = maxLines > 0 ? maxLines : COMPARISON_ROW_LAYOUT_MAX_LINES;
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length <= maxCharsPerLine) {
      current = next;
      continue;
    }
    if (current) lines.push(current);
    current = word.length > maxCharsPerLine ? word.slice(0, maxCharsPerLine) : word;
  }
  if (current) lines.push(current);
  if (lines.length === 0) return [text.slice(0, maxCharsPerLine)];
  return lines.slice(0, cap);
}

export function measureComparisonCellContentHeight(
  text: string,
  cellWidth: number,
  hasDimensionLabel: boolean,
): number {
  const pad = COMPARISON_ROW_PAD;
  const lineHeight = COMPARISON_ROW_LINE_HEIGHT;
  const maxChars = comparisonRowCharsPerLine(cellWidth, COMPARISON_ROW_FONT_SIZE, pad);
  const lines = wrapTeachingExplanationForRow(text, maxChars, COMPARISON_ROW_LAYOUT_MAX_LINES);
  const dimensionReserve = hasDimensionLabel ? TIMELINE_COMPARISON_DIMENSION_RESERVE : 0;
  return Math.max(
    COMPARISON_ROW_MIN_H,
    dimensionReserve + lines.length * lineHeight + pad * 2,
  );
}

/** Stack row pairs with dynamic height so long text is never clipped by a fixed box. */
export function reflowComparisonRowUnits(units: ComparisonRowUnit[]): ComparisonRowUnit[] {
  if (units.length === 0) return units;
  const sorted = [...units].sort((a, b) => a.pairIndex - b.pairIndex);
  const anchor = sorted.find((u) => u.phase !== "hidden");
  let y = anchor?.left?.box.y ?? anchor?.right?.box.y ?? anchor?.rowBox.y ?? 0;

  return sorted.map((unit) => {
    if (unit.phase === "hidden") return unit;

    const isActive = unit.phase === "active";
    const showDimension = Boolean(unit.dimension && isActive);
    const leftW = unit.left?.box.w ?? unit.right?.box.w ?? 200;
    const rightW = unit.right?.box.w ?? unit.left?.box.w ?? 200;
    const leftH = unit.left
      ? measureComparisonCellContentHeight(unit.left.text, leftW, showDimension)
      : 0;
    const rightH = unit.right
      ? measureComparisonCellContentHeight(unit.right.text, rightW, showDimension)
      : 0;
    const h = Math.max(COMPARISON_ROW_MIN_H, leftH, rightH);

    const left = unit.left ? { ...unit.left, box: { ...unit.left.box, y, h } } : null;
    const right = unit.right ? { ...unit.right, box: { ...unit.right.box, y, h } } : null;
    const rowBox = rowBoxFromCells(left, right);

    const next = { ...unit, left, right, rowBox };
    y += h + COMPARISON_ROW_GAP;
    return next;
  });
}
