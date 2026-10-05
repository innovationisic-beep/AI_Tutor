/**
 * Geometry helpers for paint-style Visual Teaching region authoring.
 * All values are normalized image coordinates in [0, 1].
 *
 * Draw / move / resize share the same normalized space (fit-box content coords).
 */
import type { RegionShape } from "./types";

export type DrawTool = "rectangle" | "square" | "circle" | "arrow";

export type NormPt = { x: number; y: number };
export type NormRect = { x: number; y: number; w: number; h: number };
export type NormEllipse = { cx: number; cy: number; rx: number; ry: number };

/** Minimum usable region size in normalized space (~4% of image). */
export const MIN_NORM_SIZE = 0.04;

/** Minimum label chrome size. */
export const MIN_LABEL_W = 0.12;
export const MIN_LABEL_H = 0.05;

/** Below this drag distance, pointer-up does not commit a new shape. */
export const MIN_DRAG_COMMIT = 0.025;

export type ResizeHandle = "nw" | "ne" | "sw" | "se";

export function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0;
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

/** Map authoring tool → persisted region shape (circle → ellipse). Arrow is not a region. */
export function toolToRegionShape(
  tool: Exclude<DrawTool, "arrow">
): RegionShape {
  if (tool === "circle") return "ellipse";
  return "rect";
}

export function dragDistance(a: NormPt, b: NormPt): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

export function isMeaningfulDrag(a: NormPt, b: NormPt): boolean {
  return dragDistance(a, b) >= MIN_DRAG_COMMIT;
}

/**
 * Axis-aligned rect from two opposite corners (any drag direction).
 * Square mode: side = max(|dx|,|dy|), expands from origin in drag quadrant.
 */
export function dragToRect(
  a: NormPt,
  b: NormPt,
  opts?: { square?: boolean; minSize?: number }
): NormRect {
  const minSize = opts?.minSize ?? MIN_NORM_SIZE;
  const square = Boolean(opts?.square);
  let x0 = a.x;
  let y0 = a.y;
  let x1 = b.x;
  let y1 = b.y;

  if (square) {
    const dx = x1 - x0;
    const dy = y1 - y0;
    const side = Math.max(Math.abs(dx), Math.abs(dy), minSize);
    const sx = dx < 0 ? -1 : 1;
    const sy = dy < 0 ? -1 : 1;
    x1 = x0 + sx * side;
    y1 = y0 + sy * side;
  }

  let x = Math.min(x0, x1);
  let y = Math.min(y0, y1);
  let w = Math.abs(x1 - x0);
  let h = Math.abs(y1 - y0);

  // Clamp into unit square while preserving as much size as possible.
  if (x < 0) {
    w += x;
    x = 0;
  }
  if (y < 0) {
    h += y;
    y = 0;
  }
  if (x + w > 1) w = 1 - x;
  if (y + h > 1) h = 1 - y;

  w = Math.max(minSize, w);
  h = Math.max(minSize, h);
  if (x + w > 1) x = Math.max(0, 1 - w);
  if (y + h > 1) y = Math.max(0, 1 - h);

  if (square) {
    const side = Math.min(w, h);
    return { x, y, w: side, h: side };
  }
  return { x, y, w, h };
}

/**
 * Circle from corner-to-corner drag (Word/Paint style):
 * equal bounding box → ellipse with rx === ry.
 */
export function dragToCircle(
  a: NormPt,
  b: NormPt,
  opts?: { minSize?: number }
): NormEllipse {
  const box = dragToRect(a, b, { square: true, minSize: opts?.minSize });
  return rectToCircle(box);
}

export function rectToCircle(box: NormRect): NormEllipse {
  const side = Math.min(box.w, box.h);
  const rx = Math.max(MIN_NORM_SIZE / 2, side / 2);
  const ry = rx;
  return {
    cx: clamp01(box.x + side / 2),
    cy: clamp01(box.y + side / 2),
    rx,
    ry,
  };
}

export function ellipseToRect(g: NormEllipse): NormRect {
  return {
    x: g.cx - g.rx,
    y: g.cy - g.ry,
    w: g.rx * 2,
    h: g.ry * 2,
  };
}

/** Move rect by delta; size unchanged; clamped inside [0,1]. */
export function moveRect(g: NormRect, dx: number, dy: number): NormRect {
  const w = Math.max(MIN_NORM_SIZE, Math.min(1, g.w));
  const h = Math.max(MIN_NORM_SIZE, Math.min(1, g.h));
  const x = Math.min(Math.max(0, g.x + dx), Math.max(0, 1 - w));
  const y = Math.min(Math.max(0, g.y + dy), Math.max(0, 1 - h));
  return { x, y, w, h };
}

/** Move ellipse by delta; radii unchanged; center clamped so ellipse stays in bounds. */
export function moveEllipse(g: NormEllipse, dx: number, dy: number): NormEllipse {
  const rx = Math.max(MIN_NORM_SIZE / 2, g.rx);
  const ry = Math.max(MIN_NORM_SIZE / 2, g.ry);
  const cx = Math.min(Math.max(rx, g.cx + dx), 1 - rx);
  const cy = Math.min(Math.max(ry, g.cy + dy), 1 - ry);
  return { cx, cy, rx, ry };
}

/** Opposite corner from a resize handle (stays fixed during resize). */
export function oppositeCorner(
  g: NormRect,
  handle: ResizeHandle
): NormPt {
  if (handle === "nw") return { x: g.x + g.w, y: g.y + g.h };
  if (handle === "ne") return { x: g.x, y: g.y + g.h };
  if (handle === "sw") return { x: g.x + g.w, y: g.y };
  return { x: g.x, y: g.y }; // se → nw fixed
}

/**
 * Resize rect from initial geometry + current pointer.
 * Opposite corner stays fixed. Optional 1:1 lock for squares.
 */
export function resizeRect(
  initial: NormRect,
  handle: ResizeHandle,
  pt: NormPt,
  opts?: { lockAspect?: boolean; minSize?: number }
): NormRect {
  const anchor = oppositeCorner(initial, handle);
  return dragToRect(anchor, pt, {
    square: Boolean(opts?.lockAspect),
    minSize: opts?.minSize,
  });
}

/**
 * Resize circle/ellipse from handle: treat bbox corners, keep rx===ry when locked.
 */
export function resizeCircle(
  initial: NormEllipse,
  handle: ResizeHandle,
  pt: NormPt,
  opts?: { minSize?: number }
): NormEllipse {
  const box = ellipseToRect(initial);
  const next = resizeRect(box, handle, pt, {
    lockAspect: true,
    minSize: opts?.minSize,
  });
  return rectToCircle(next);
}

/** True when a stored rect should resize as a square (near 1:1). */
export function isNearSquare(g: NormRect, eps = 1e-3): boolean {
  return Math.abs(g.w - g.h) <= eps;
}

/** True when ellipse is a circle (rx≈ry). */
export function isCircleEllipse(g: NormEllipse, eps = 1e-3): boolean {
  return Math.abs(g.rx - g.ry) <= eps;
}

export function pointInRect(pt: NormPt, g: NormRect): boolean {
  return pt.x >= g.x && pt.x <= g.x + g.w && pt.y >= g.y && pt.y <= g.y + g.h;
}

export function pointInEllipse(pt: NormPt, g: NormEllipse): boolean {
  const dx = (pt.x - g.cx) / Math.max(g.rx, 1e-6);
  const dy = (pt.y - g.cy) / Math.max(g.ry, 1e-6);
  return dx * dx + dy * dy <= 1;
}

export function rectHandles(
  g: NormRect
): Record<ResizeHandle, NormPt> {
  return {
    nw: { x: g.x, y: g.y },
    ne: { x: g.x + g.w, y: g.y },
    sw: { x: g.x, y: g.y + g.h },
    se: { x: g.x + g.w, y: g.y + g.h },
  };
}

export function ellipseHandles(
  g: NormEllipse
): Record<ResizeHandle, NormPt> {
  return rectHandles(ellipseToRect(g));
}

/**
 * Hit-test resize handles. `tol` is in normalized units.
 * Prefer a floor so small shapes remain resizeable.
 */
export function hitResizeHandle(
  pt: NormPt,
  handles: Record<ResizeHandle, NormPt>,
  tol = 0.04
): ResizeHandle | null {
  let best: ResizeHandle | null = null;
  let bestDist = tol;
  for (const key of ["nw", "ne", "sw", "se"] as ResizeHandle[]) {
    const h = handles[key];
    const d = Math.hypot(pt.x - h.x, pt.y - h.y);
    if (d <= bestDist) {
      bestDist = d;
      best = key;
    }
  }
  return best;
}

export function cursorForHandle(handle: ResizeHandle): string {
  if (handle === "nw" || handle === "se") return "nwse-resize";
  return "nesw-resize";
}

/** Clamp a label chrome box into the unit square with min size. */
export function clampLabelBox(g: NormRect): NormRect {
  const w = Math.max(MIN_LABEL_W, Math.min(0.55, g.w));
  const h = Math.max(MIN_LABEL_H, Math.min(0.2, g.h));
  const x = Math.min(Math.max(0, g.x), 1 - w);
  const y = Math.min(Math.max(0, g.y), 1 - h);
  return { x, y, w, h };
}

/** Default label box above a focus point. */
export function defaultLabelBoxNear(
  focus: NormPt,
  textLen = 8
): NormRect {
  const h = Math.max(MIN_LABEL_H, 0.055);
  const w = Math.min(0.45, Math.max(MIN_LABEL_W, textLen * 0.014 + 0.1));
  return clampLabelBox({
    x: focus.x - w * 0.1,
    y: focus.y - h - 0.012,
    w,
    h,
  });
}

export function moveLabelBox(g: NormRect, dx: number, dy: number): NormRect {
  return clampLabelBox({ ...g, x: g.x + dx, y: g.y + dy });
}

/** Resize label from SE handle (opposite NW fixed) — free aspect for text chrome. */
export function resizeLabelBox(
  initial: NormRect,
  handle: ResizeHandle,
  pt: NormPt
): NormRect {
  return clampLabelBox(resizeRect(initial, handle, pt, { minSize: MIN_LABEL_H }));
}

/**
 * Convert client pointer → normalized image content coords using the same
 * fit-box letterboxing as VisualTeachingStage.
 */
export function clientToNorm(
  clientX: number,
  clientY: number,
  containerRect: { left: number; top: number },
  box: { x: number; y: number; width: number; height: number },
  opts?: { clamp?: boolean }
): NormPt | null {
  if (box.width <= 0 || box.height <= 0) return null;
  let x = (clientX - containerRect.left - box.x) / box.width;
  let y = (clientY - containerRect.top - box.y) / box.height;
  if (opts?.clamp) {
    return { x: clamp01(x), y: clamp01(y) };
  }
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return { x, y };
}
