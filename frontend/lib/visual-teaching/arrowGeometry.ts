/**
 * Arrow geometry helpers for Visual Teaching overlays & authoring.
 * Normalized coords are 0..1; SVG helpers use viewBox units.
 */

export type Pt = { x: number; y: number };

export function arrowEndpointIds(connectionId: string): {
  from: string;
  to: string;
} {
  return {
    from: `${connectionId}_from`,
    to: `${connectionId}_to`,
  };
}

export function isArrowEndpointAnchor(
  anchorId: string,
  connectionId: string
): boolean {
  const ids = arrowEndpointIds(connectionId);
  return anchorId === ids.from || anchorId === ids.to;
}

export function nextArrowConnectionId(existingIds: string[]): string {
  const used = new Set(existingIds);
  let n = 1;
  while (used.has(`arrow_${n}`)) n += 1;
  return `arrow_${n}`;
}

/** Distance from point to segment AB in normalized space. */
export function distToSegment(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-12) return Math.hypot(p.x - a.x, p.y - a.y);
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const qx = a.x + t * dx;
  const qy = a.y + t * dy;
  return Math.hypot(p.x - qx, p.y - qy);
}

export type ArrowHit = "from" | "to" | "body";

/** Hit-test an arrow: endpoints preferred, then body. */
export function hitArrow(
  pt: Pt,
  from: Pt,
  to: Pt,
  opts?: { endTol?: number; bodyTol?: number }
): ArrowHit | null {
  const endTol = opts?.endTol ?? 0.04;
  const bodyTol = opts?.bodyTol ?? 0.03;
  if (Math.hypot(pt.x - from.x, pt.y - from.y) <= endTol) return "from";
  if (Math.hypot(pt.x - to.x, pt.y - to.y) <= endTol) return "to";
  if (distToSegment(pt, from, to) <= bodyTol) return "body";
  return null;
}

/** Shorten a line so the arrowhead sits clear of endpoints (SVG units). */
export function shortenArrowLine(
  from: Pt,
  to: Pt,
  opts?: { startInset?: number; endInset?: number }
): { x1: number; y1: number; x2: number; y2: number } | null {
  const startInset = opts?.startInset ?? 14;
  const endInset = opts?.endInset ?? 36;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy);
  if (!Number.isFinite(len) || len < 8) return null;
  const ux = dx / len;
  const uy = dy / len;
  const start = Math.min(startInset, len * 0.25);
  const end = Math.min(endInset, len * 0.35);
  if (start + end >= len - 2) {
    return { x1: from.x, y1: from.y, x2: to.x, y2: to.y };
  }
  return {
    x1: from.x + ux * start,
    y1: from.y + uy * start,
    x2: to.x - ux * end,
    y2: to.y - uy * end,
  };
}

export function arrowLabelPoint(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  offset = 14
): Pt {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  return { x: mx + (-dy / len) * offset, y: my + (dx / len) * offset };
}

export function clamp01Pt(p: Pt): Pt {
  return {
    x: Math.min(1, Math.max(0, p.x)),
    y: Math.min(1, Math.max(0, p.y)),
  };
}
