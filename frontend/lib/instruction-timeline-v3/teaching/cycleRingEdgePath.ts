import { CYCLE_RING_CY_RATIO } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import type { ViewportBox } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";

const MIN_CYCLE_EDGE_LEN = 18;

function anchorOnBoxToward(
  box: ViewportBox,
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

/** Resolve cycle edge anchors; handles nearby bottom-arc nodes (e.g. 5-step rings). */
export function resolveCycleRingEdgeAnchors(
  fromN: ViewportBox,
  toN: ViewportBox,
): { x1: number; y1: number; x2: number; y2: number } {
  const toCx = toN.x + toN.w / 2;
  const toCy = toN.y + toN.h / 2;
  const fromCx = fromN.x + fromN.w / 2;
  const fromCy = fromN.y + fromN.h / 2;

  let p1 = anchorOnBoxToward(fromN, toCx, toCy);
  let p2 = anchorOnBoxToward(toN, fromCx, fromCy);
  let len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
  if (len >= MIN_CYCLE_EDGE_LEN) {
    return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
  }

  const dx = toCx - fromCx;
  const dy = toCy - fromCy;
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);

  if (absDx >= absDy) {
    // Nearly horizontal ring segment — route along the shared bottom or top edge.
    const sharedLower = fromCy > toCy ? fromCy : toCy;
    const useBottom = sharedLower >= (fromCy + toCy) / 2;
    if (useBottom) {
      p1 = { x: fromCx, y: fromN.y + fromN.h };
      p2 = { x: toCx, y: toN.y + toN.h };
    } else {
      p1 = { x: fromCx, y: fromN.y };
      p2 = { x: toCx, y: toN.y };
    }
  } else if (dx > 0) {
    p1 = { x: fromN.x + fromN.w, y: fromCy };
    p2 = { x: toN.x, y: toCy };
  } else {
    p1 = { x: fromN.x, y: fromCy };
    p2 = { x: toN.x + toN.w, y: toCy };
  }

  len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
  if (len >= MIN_CYCLE_EDGE_LEN) {
    return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
  }

  return { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
}

export function cycleRingCenter(
  width: number,
  height: number,
): { cx: number; cy: number } {
  return { cx: width / 2, cy: height * CYCLE_RING_CY_RATIO };
}

/** Cubic path for a cycle-ring edge following clockwise exterior flow. */
export function cycleRingEdgePath(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  viewport: { width: number; height: number },
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const { cx, cy } = cycleRingCenter(viewport.width, viewport.height);
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const toCenterX = cx - mx;
  const toCenterY = cy - my;
  const dist = Math.hypot(toCenterX, toCenterY) || 1;
  const nx = toCenterX / dist;
  const ny = toCenterY / dist;
  const bulge = Math.min(90, Math.max(28, Math.hypot(dx, dy) * 0.4));

  // Lower-hemisphere arcs: stay on the clockwise exterior but lift upward so edges
  // clear below-node callouts without routing inward (which reverses visible flow).
  const lowerHemisphere = my > cy - 10;
  const lift = lowerHemisphere ? Math.min(52, Math.max(18, bulge * 0.48)) : 0;

  const c1x = x1 + dx * 0.33 - nx * bulge * 0.55;
  const c1y = y1 + dy * 0.33 - ny * bulge * 0.55 - lift;
  const c2x = x2 - dx * 0.28 - nx * bulge * 0.45;
  const c2y = y2 - dy * 0.28 - ny * bulge * 0.45 - lift * 0.85;

  return `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`;
}

/** True when the end tangent of the cubic points opposite the intended chord direction. */
export function cycleRingEdgeMarkerReversed(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  viewport: { width: number; height: number },
): boolean {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const { cx, cy } = cycleRingCenter(viewport.width, viewport.height);
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const toCenterX = cx - mx;
  const toCenterY = cy - my;
  const dist = Math.hypot(toCenterX, toCenterY) || 1;
  const nx = toCenterX / dist;
  const ny = toCenterY / dist;
  const bulge = Math.min(90, Math.max(28, Math.hypot(dx, dy) * 0.4));
  const lowerHemisphere = my > cy - 10;
  const lift = lowerHemisphere ? Math.min(52, Math.max(18, bulge * 0.48)) : 0;
  const c2x = x2 - dx * 0.28 - nx * bulge * 0.45;
  const c2y = y2 - dy * 0.28 - ny * bulge * 0.45 - lift * 0.85;
  const tx = x2 - c2x;
  const ty = y2 - c2y;
  return tx * dx + ty * dy < 0;
}
