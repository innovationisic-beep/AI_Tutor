import type {
  EllipseGeometry,
  NormPoint,
  PointGeometry,
  PolygonGeometry,
  RectGeometry,
  RegionGeometry,
  RegionShape,
  VisualTeachingConnection,
  VisualTeachingRegion,
} from "./types";
import { SVG_VIEWBOX } from "./types";

export function clamp01(v: unknown, fallback = 0): number {
  const x = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(x)) return fallback;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

export function validateRegionGeometry(
  shape: RegionShape,
  geometry: unknown
): { ok: true } | { ok: false; message: string } {
  if (!geometry || typeof geometry !== "object") {
    return { ok: false, message: "geometry must be an object" };
  }
  const g = geometry as Record<string, unknown>;
  if (shape === "point") {
    if (!("x" in g) || !("y" in g)) return { ok: false, message: "point requires x,y" };
    return { ok: true };
  }
  if (shape === "rect") {
    for (const k of ["x", "y", "w", "h"] as const) {
      if (!(k in g)) return { ok: false, message: "rect requires x,y,w,h" };
    }
    if (Number(g.w) <= 0 || Number(g.h) <= 0) {
      return { ok: false, message: "rect w/h must be > 0" };
    }
    return { ok: true };
  }
  if (shape === "ellipse") {
    for (const k of ["cx", "cy", "rx", "ry"] as const) {
      if (!(k in g)) return { ok: false, message: "ellipse requires cx,cy,rx,ry" };
    }
    if (Number(g.rx) <= 0 || Number(g.ry) <= 0) {
      return { ok: false, message: "ellipse rx/ry must be > 0" };
    }
    return { ok: true };
  }
  if (shape === "polygon") {
    const pts = g.points;
    if (!Array.isArray(pts) || pts.length < 3) {
      return { ok: false, message: "polygon requires ≥3 points" };
    }
    for (const p of pts) {
      if (!p || typeof p !== "object" || !("x" in p) || !("y" in p)) {
        return { ok: false, message: "polygon points must be {x,y}" };
      }
    }
    return { ok: true };
  }
  return { ok: false, message: `unknown shape ${shape}` };
}

export function normalizeRegionGeometry(
  shape: RegionShape,
  geometry: unknown
): RegionGeometry {
  const g =
    geometry && typeof geometry === "object"
      ? (geometry as Record<string, unknown>)
      : {};
  if (shape === "point") {
    return { x: clamp01(g.x), y: clamp01(g.y) } satisfies PointGeometry;
  }
  if (shape === "rect") {
    return {
      x: clamp01(g.x),
      y: clamp01(g.y),
      w: clamp01(g.w, 0.01),
      h: clamp01(g.h, 0.01),
    } satisfies RectGeometry;
  }
  if (shape === "ellipse") {
    return {
      cx: clamp01(g.cx),
      cy: clamp01(g.cy),
      rx: clamp01(g.rx, 0.01),
      ry: clamp01(g.ry, 0.01),
    } satisfies EllipseGeometry;
  }
  const pts = Array.isArray(g.points) ? g.points : [];
  return {
    points: pts
      .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
      .map((p) => ({ x: clamp01(p.x), y: clamp01(p.y) })),
  } satisfies PolygonGeometry;
}

function pointInPolygon(x: number, y: number, pts: NormPoint[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i]!.x;
    const yi = pts[i]!.y;
    const xj = pts[j]!.x;
    const yj = pts[j]!.y;
    const intersect =
      yi > y !== yj > y &&
      x < ((xj - xi) * (y - yi)) / (yj - yi + Number.EPSILON) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function distToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 <= Number.EPSILON) {
    const ox = px - ax;
    const oy = py - ay;
    return Math.hypot(ox, oy);
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function minDistToEdges(x: number, y: number, pts: NormPoint[]): number {
  let best = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]!;
    const b = pts[(i + 1) % pts.length]!;
    best = Math.min(best, distToSegment(x, y, a.x, a.y, b.x, b.y));
  }
  return best;
}

function polygonCentroid(pts: NormPoint[]): NormPoint {
  let sx = 0;
  let sy = 0;
  for (const p of pts) {
    sx += p.x;
    sy += p.y;
  }
  const n = Math.max(1, pts.length);
  return { x: sx / n, y: sy / n };
}

/**
 * Pole-of-inaccessibility heuristic for a normalized polygon.
 * Never returns the raw centroid alone unless it is inside and best-of-grid.
 */
export function poleOfInaccessibility(pts: NormPoint[]): NormPoint {
  if (pts.length < 3) return pts[0] ?? { x: 0.5, y: 0.5 };

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of pts) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }

  const centroid = polygonCentroid(pts);
  let best = centroid;
  let bestDist = pointInPolygon(centroid.x, centroid.y, pts)
    ? minDistToEdges(centroid.x, centroid.y, pts)
    : -1;

  const grid = 24;
  for (let gy = 0; gy <= grid; gy++) {
    for (let gx = 0; gx <= grid; gx++) {
      const x = minX + ((maxX - minX) * gx) / grid;
      const y = minY + ((maxY - minY) * gy) / grid;
      if (!pointInPolygon(x, y, pts)) continue;
      const d = minDistToEdges(x, y, pts);
      if (d > bestDist) {
        bestDist = d;
        best = { x, y };
      }
    }
  }

  // Refine around best with a denser local grid.
  if (bestDist >= 0) {
    const spanX = (maxX - minX) / grid;
    const spanY = (maxY - minY) / grid;
    for (let gy = -4; gy <= 4; gy++) {
      for (let gx = -4; gx <= 4; gx++) {
        const x = clamp01(best.x + (gx * spanX) / 4);
        const y = clamp01(best.y + (gy * spanY) / 4);
        if (!pointInPolygon(x, y, pts)) continue;
        const d = minDistToEdges(x, y, pts);
        if (d > bestDist) {
          bestDist = d;
          best = { x, y };
        }
      }
    }
  }

  if (bestDist < 0) {
    // Degenerate / self-intersecting — return bbox center clamped inside-ish.
    return {
      x: clamp01((minX + maxX) / 2),
      y: clamp01((minY + maxY) / 2),
    };
  }
  return { x: clamp01(best.x), y: clamp01(best.y) };
}

/** Resolve pointer/label focus in normalized image space. */
export function resolveFocusPoint(region: VisualTeachingRegion): NormPoint {
  const fp = region.focus_point;
  if (
    fp &&
    typeof fp.x === "number" &&
    typeof fp.y === "number" &&
    Number.isFinite(fp.x) &&
    Number.isFinite(fp.y)
  ) {
    return { x: clamp01(fp.x), y: clamp01(fp.y) };
  }

  const shape = region.shape;
  const g = normalizeRegionGeometry(shape, region.geometry);

  if (shape === "point") {
    const p = g as PointGeometry;
    return { x: p.x, y: p.y };
  }
  if (shape === "rect") {
    const r = g as RectGeometry;
    return { x: clamp01(r.x + r.w / 2), y: clamp01(r.y + r.h / 2) };
  }
  if (shape === "ellipse") {
    const e = g as EllipseGeometry;
    return { x: e.cx, y: e.cy };
  }
  const poly = g as PolygonGeometry;
  return poleOfInaccessibility(poly.points);
}

/**
 * Resolve label chrome box in normalized space.
 * Uses authored label_box when present; otherwise a default above the focus point.
 */
export function resolveLabelBox(region: VisualTeachingRegion): RectGeometry {
  const lb = region.label_box;
  if (
    lb &&
    typeof lb.x === "number" &&
    typeof lb.y === "number" &&
    typeof lb.w === "number" &&
    typeof lb.h === "number" &&
    Number.isFinite(lb.x) &&
    Number.isFinite(lb.y) &&
    Number.isFinite(lb.w) &&
    Number.isFinite(lb.h)
  ) {
    const w = Math.max(0.08, Math.min(0.55, lb.w));
    const h = Math.max(0.035, Math.min(0.2, lb.h));
    return {
      x: clamp01(Math.min(lb.x, 1 - w)),
      y: clamp01(Math.min(lb.y, 1 - h)),
      w,
      h,
    };
  }
  const fp = resolveFocusPoint(region);
  const text = (region.label?.trim() || region.region_id || "label").length;
  const h = 0.045;
  const w = Math.min(0.4, Math.max(0.08, text * 0.012 + 0.06));
  return {
    x: clamp01(Math.min(fp.x - w * 0.1, 1 - w)),
    y: clamp01(Math.max(0, fp.y - h - 0.012)),
    w,
    h,
  };
}

/**
 * Resolve arrow label chrome box. Uses authored label_box when present;
 * otherwise defaults near the arrow midpoint (offset slightly above).
 */
export function resolveConnectionLabelBox(
  connection: Pick<
    VisualTeachingConnection,
    "connection_id" | "label" | "label_box"
  >,
  from: NormPoint,
  to: NormPoint
): RectGeometry {
  const lb = connection.label_box;
  if (
    lb &&
    typeof lb.x === "number" &&
    typeof lb.y === "number" &&
    typeof lb.w === "number" &&
    typeof lb.h === "number" &&
    Number.isFinite(lb.x) &&
    Number.isFinite(lb.y) &&
    Number.isFinite(lb.w) &&
    Number.isFinite(lb.h)
  ) {
    const w = Math.max(0.12, Math.min(0.55, lb.w));
    const h = Math.max(0.05, Math.min(0.2, lb.h));
    return {
      x: clamp01(Math.min(lb.x, 1 - w)),
      y: clamp01(Math.min(lb.y, 1 - h)),
      w,
      h,
    };
  }
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2;
  const text = (
    connection.label?.trim() ||
    connection.connection_id ||
    "label"
  ).length;
  const h = 0.055;
  const w = Math.min(0.45, Math.max(0.12, text * 0.014 + 0.1));
  return {
    x: clamp01(Math.min(mx - w * 0.5, 1 - w)),
    y: clamp01(Math.max(0, my - h - 0.02)),
    w,
    h,
  };
}

function toSvg(n: number): number {
  return clamp01(n) * SVG_VIEWBOX;
}

export type SvgRegionPath = {
  region_id: string;
  shape: RegionShape;
  /** Path `d` for closed shapes; unused for point. */
  d?: string;
  /** Circle center/radius for point markers. */
  cx?: number;
  cy?: number;
  r?: number;
  /** Ellipse attributes. */
  rx?: number;
  ry?: number;
};

/** Convert region geometries to SVG coords in viewBox 0..1000. */
export function geometryToSvgPaths(
  regions: VisualTeachingRegion[]
): SvgRegionPath[] {
  return regions.map((region) => {
    const shape = region.shape;
    const g = normalizeRegionGeometry(shape, region.geometry);
    if (shape === "point") {
      const p = g as PointGeometry;
      return {
        region_id: region.region_id,
        shape,
        cx: toSvg(p.x),
        cy: toSvg(p.y),
        r: 10,
      };
    }
    if (shape === "rect") {
      const r = g as RectGeometry;
      const x = toSvg(r.x);
      const y = toSvg(r.y);
      const w = Math.max(1, r.w * SVG_VIEWBOX);
      const h = Math.max(1, r.h * SVG_VIEWBOX);
      return {
        region_id: region.region_id,
        shape,
        d: `M ${x} ${y} h ${w} v ${h} h ${-w} Z`,
      };
    }
    if (shape === "ellipse") {
      const e = g as EllipseGeometry;
      return {
        region_id: region.region_id,
        shape,
        cx: toSvg(e.cx),
        cy: toSvg(e.cy),
        rx: Math.max(1, e.rx * SVG_VIEWBOX),
        ry: Math.max(1, e.ry * SVG_VIEWBOX),
      };
    }
    const poly = g as PolygonGeometry;
    const pts = poly.points;
    if (pts.length === 0) {
      return { region_id: region.region_id, shape, d: "" };
    }
    const head = `M ${toSvg(pts[0]!.x)} ${toSvg(pts[0]!.y)}`;
    const rest = pts
      .slice(1)
      .map((p) => `L ${toSvg(p.x)} ${toSvg(p.y)}`)
      .join(" ");
    return {
      region_id: region.region_id,
      shape,
      d: `${head} ${rest} Z`,
    };
  });
}

export function regionById(
  regions: VisualTeachingRegion[],
  id: string | null | undefined
): VisualTeachingRegion | undefined {
  if (!id) return undefined;
  return regions.find((r) => r.region_id === id);
}
