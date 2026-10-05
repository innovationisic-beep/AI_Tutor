import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

export type ComparisonSide = "left" | "right";
export type ComparisonTier = "header" | "row";

export interface ComparisonTeachingHints {
  comparison_side?: ComparisonSide;
  comparison_tier?: ComparisonTier;
  pair_index?: number;
  semantic_role?: string;
}

export interface ComparisonNodeHints {
  side: ComparisonSide;
  tier: ComparisonTier;
  order: number;
}

export interface ComparisonPartition {
  leftHeader: string | null;
  rightHeader: string | null;
  rows: Array<{ left: string | null; right: string | null }>;
}

/** Divider center and chrome geometry (deterministic; shared with renderer). */
export const COMPARISON_CENTER_X_RATIO = 0.5;
export const COMPARISON_DIVIDER_GAP = 40;
export const COMPARISON_SIDE_PAD = 28;
export const COMPARISON_HEADER_Y = 44;
export const COMPARISON_HEADER_H = 64;
export const COMPARISON_ROW_H = 112;
export const COMPARISON_ROW_GAP = 24;
export const COMPARISON_HEADER_TO_ROWS_GAP = 18;

function normalizeSide(raw: unknown): ComparisonSide | null {
  const s = String(raw ?? "")
    .trim()
    .toLowerCase();
  if (!s) return null;
  if (s === "left" || s.includes("left")) return "left";
  if (s === "right" || s.includes("right")) return "right";
  if (s === "a") return "left";
  if (s === "b") return "right";
  return null;
}

function isHeaderTier(raw: unknown, role?: string): boolean {
  const t = String(raw ?? "")
    .trim()
    .toLowerCase();
  if (t === "header") return true;
  const r = String(role ?? "")
    .trim()
    .toLowerCase();
  return r.includes("header") || r === "title" || r === "column_header";
}

/**
 * Resolve comparison side/tier from CIR semantic payload on a node projection,
 * with deterministic index fallback when hints are absent.
 */
export function extractComparisonHints(
  entityId: string,
  hints: ComparisonTeachingHints | undefined,
  indexInOrder: number,
  totalCount: number,
  semanticRole?: string,
): ComparisonNodeHints {
  const order = indexInOrder;
  const tier: ComparisonTier = isHeaderTier(hints?.comparison_tier, semanticRole) ? "header" : "row";

  const fromPayload = normalizeSide(hints?.comparison_side);
  if (fromPayload) {
    return { side: fromPayload, tier, order };
  }

  const leftN = Math.max(1, Math.floor((totalCount + 1) / 2));
  const side: ComparisonSide = indexInOrder < leftN ? "left" : "right";
  return { side, tier, order };
}

export function hintsFromNodeProjection(node: RenderNodeProjection | undefined): ComparisonTeachingHints | undefined {
  if (!node?.teaching_hints) return undefined;
  return node.teaching_hints;
}

/** Partition sorted node ids into headers and aligned comparison rows. */
export function partitionComparisonNodes(
  nodeIds: string[],
  hintFor: (id: string) => ComparisonNodeHints,
): ComparisonPartition {
  const order = new Map(nodeIds.map((id, i) => [id, i]));
  const byOrder = (a: string, b: string) => (order.get(a) ?? 0) - (order.get(b) ?? 0);

  const leftHeaders: string[] = [];
  const rightHeaders: string[] = [];
  const leftRows: string[] = [];
  const rightRows: string[] = [];

  for (const id of nodeIds) {
    const h = hintFor(id);
    if (h.tier === "header") {
      if (h.side === "left") leftHeaders.push(id);
      else rightHeaders.push(id);
    } else if (h.side === "left") {
      leftRows.push(id);
    } else {
      rightRows.push(id);
    }
  }

  leftHeaders.sort(byOrder);
  rightHeaders.sort(byOrder);
  leftRows.sort(byOrder);
  rightRows.sort(byOrder);

  const rowCount = Math.max(leftRows.length, rightRows.length);
  const rows: ComparisonPartition["rows"] = [];
  for (let r = 0; r < rowCount; r += 1) {
    rows.push({
      left: leftRows[r] ?? null,
      right: rightRows[r] ?? null,
    });
  }

  return {
    leftHeader: leftHeaders[0] ?? null,
    rightHeader: rightHeaders[0] ?? null,
    rows,
  };
}

export function comparisonSplitStageBounds(
  width: number,
  height: number,
  hasHeaderRow = true,
): { minX: number; minY: number; maxX: number; maxY: number } {
  const centerX = width * COMPARISON_CENTER_X_RATIO;
  const halfGap = COMPARISON_DIVIDER_GAP / 2;
  const leftColW = Math.max(
    160,
    Math.floor(centerX - halfGap - COMPARISON_SIDE_PAD) - COMPARISON_SIDE_PAD,
  );
  const rightColW = Math.max(
    160,
    Math.floor(width - centerX - halfGap - COMPARISON_SIDE_PAD) - COMPARISON_SIDE_PAD,
  );
  const leftX = COMPARISON_SIDE_PAD;
  const rightX = Math.round(centerX + halfGap);
  return {
    minX: leftX,
    minY: hasHeaderRow ? COMPARISON_HEADER_Y - 8 : COMPARISON_HEADER_Y,
    maxX: rightX + rightColW + COMPARISON_SIDE_PAD,
    maxY: height - 48,
  };
}

/** Horizontal center of the gutter between left/right columns (not raw viewBox midpoint). */
export function comparisonDividerCenterX(width: number): number {
  const centerX = width * COMPARISON_CENTER_X_RATIO;
  const halfGap = COMPARISON_DIVIDER_GAP / 2;
  const leftEnd = centerX - halfGap - COMPARISON_SIDE_PAD;
  const rightStart = centerX + halfGap;
  return (leftEnd + rightStart) / 2;
}

export function resolveComparisonDividerCenterX(
  width: number,
  nodes: ReadonlyArray<Pick<RenderNodeProjection, "viewport_box" | "teaching_hints">>,
): number {
  const leftHeader = nodes.find(
    (n) =>
      n.teaching_hints?.comparison_tier === "header" && n.teaching_hints?.comparison_side === "left",
  );
  const rightHeader = nodes.find(
    (n) =>
      n.teaching_hints?.comparison_tier === "header" && n.teaching_hints?.comparison_side === "right",
  );
  if (leftHeader && rightHeader) {
    const leftEnd = leftHeader.viewport_box.x + leftHeader.viewport_box.w;
    const rightStart = rightHeader.viewport_box.x;
    if (rightStart > leftEnd + 4) {
      return (leftEnd + rightStart) / 2;
    }
  }
  return comparisonDividerCenterX(width);
}

function isComparisonHeaderNode(
  node: Pick<RenderNodeProjection, "teaching_hints">,
): boolean {
  return (
    node.teaching_hints?.comparison_tier === "header" ||
    String(node.teaching_hints?.semantic_role ?? "")
      .toLowerCase()
      .includes("header")
  );
}

/**
 * Divider runs from the header to the last row, plus a small pad.
 * It does not extend to the placement-canvas bottom.
 */
export function comparisonDividerGeometry(
  width: number,
  hasHeaderRow: boolean,
  contentBottom: number,
  dividerCenterX?: number,
): {
  centerX: number;
  topY: number;
  bottomY: number;
} {
  const centerX = dividerCenterX ?? comparisonDividerCenterX(width);
  const topY = hasHeaderRow ? COMPARISON_HEADER_Y - 8 : COMPARISON_HEADER_Y + 12;
  const bottomY = Math.max(topY + 24, contentBottom);
  return { centerX, topY, bottomY };
}

export function comparisonDividerForNodes(
  width: number,
  nodes: ReadonlyArray<Pick<RenderNodeProjection, "visible" | "teaching_hints" | "viewport_box">>,
  inkMaxY: number,
  pad: number,
): { centerX: number; topY: number; bottomY: number } | null {
  const visibleHeaders = nodes.filter((node) => node.visible && isComparisonHeaderNode(node));
  const hasLeft = visibleHeaders.some((node) => node.teaching_hints?.comparison_side === "left");
  const hasRight = visibleHeaders.some((node) => node.teaching_hints?.comparison_side === "right");
  if (!hasLeft || !hasRight) return null;
  const centerX = resolveComparisonDividerCenterX(width, nodes);
  return comparisonDividerGeometry(width, visibleHeaders.length > 0, inkMaxY + pad, centerX);
}
