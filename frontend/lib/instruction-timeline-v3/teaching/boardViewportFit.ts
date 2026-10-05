import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { instructionLifecycleDebugEnabled } from "@/lib/learning/instructionLifecycle";

/** Allow modest upscale when the laid-out scene is small so teaching boards fill the viewport (cap avoids blur). */
const MAX_BOARD_UPSCALE = 1.12;

export type BoardFitLogPayload = {
  content_bounds: { minX: number; minY: number; maxX: number; maxY: number };
  viewport_bounds: { width: number; height: number };
  scale: number;
  translate: { tx: number; ty: number };
  layout_mode?: string;
  projection_count?: number;
};

export type BoardFitPadding =
  | number
  | { top: number; right: number; bottom: number; left: number };

function normalizePadding(p: BoardFitPadding): { top: number; right: number; bottom: number; left: number } {
  return typeof p === "number"
    ? { top: p, right: p, bottom: p, left: p }
    : p;
}

export type ContentBounds = { minX: number; minY: number; maxX: number; maxY: number };

/** Small margin around ink once the 1040-tall placement canvas is cropped away. */
export const BOARD_DISPLAY_PAD = 24;

export const BOARD_FIT_PADDING: BoardFitPadding = { top: 28, right: 34, bottom: 88, left: 34 };
export const HIERARCHY_BOARD_FIT_PADDING: BoardFitPadding = { top: 8, right: 34, bottom: 88, left: 34 };
export const PROCESS_BOARD_FIT_PADDING: BoardFitPadding = { top: 10, right: 16, bottom: 28, left: 16 };

export function contentBoundsFromProjections(
  projections: RenderProjection[],
  options?: { includeInvisible?: boolean },
): ContentBounds | null {
  const includeInvisible = options?.includeInvisible === true;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of projections) {
    if (!includeInvisible && !p.visible) continue;
    const b = p.viewport_box;
    minX = Math.min(minX, b.x);
    minY = Math.min(minY, b.y);
    maxX = Math.max(maxX, b.x + b.w);
    maxY = Math.max(maxY, b.y + b.h);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
  return { minX, minY, maxX, maxY };
}

export function mergeContentBounds(
  base: ContentBounds | null,
  extra: ContentBounds | null,
): ContentBounds | null {
  if (!base) return extra;
  if (!extra) return base;
  return {
    minX: Math.min(base.minX, extra.minX),
    minY: Math.min(base.minY, extra.minY),
    maxX: Math.max(base.maxX, extra.maxX),
    maxY: Math.max(base.maxY, extra.maxY),
  };
}

export type BoardFitVerticalAlign = "center" | "top";

export function computeBoardFitTransformFromBounds(
  bounds: ContentBounds,
  viewWidth: number,
  viewHeight: number,
  padding: BoardFitPadding,
  verticalAlign: BoardFitVerticalAlign = "center",
  maxUpscale?: number,
): string {
  const pad = normalizePadding(padding);
  const bw = Math.max(bounds.maxX - bounds.minX, 1);
  const bh = Math.max(bounds.maxY - bounds.minY, 1);
  const innerW = Math.max(viewWidth - pad.left - pad.right, 1);
  const innerH = Math.max(viewHeight - pad.top - pad.bottom, 1);
  const rawScale = Math.min(innerW / bw, innerH / bh);
  const cap = maxUpscale ?? MAX_BOARD_UPSCALE;
  const scale = rawScale > 1 ? Math.min(rawScale, cap) : rawScale;
  const tx = pad.left + (innerW - bw * scale) / 2 - bounds.minX * scale;
  const ty =
    verticalAlign === "top"
      ? pad.top - bounds.minY * scale
      : pad.top + (innerH - bh * scale) / 2 - bounds.minY * scale;
  return `translate(${tx},${ty}) scale(${scale})`;
}

/**
 * Uniform scale + translate so all visible projections fit inside the viewBox with padding.
 */
export function computeBoardFitTransform(
  projections: RenderProjection[],
  viewWidth: number,
  viewHeight: number,
  padding: BoardFitPadding,
  verticalAlign: BoardFitVerticalAlign = "center",
  maxUpscale?: number,
): string | null {
  const bounds = contentBoundsFromProjections(projections);
  if (!bounds) return null;
  return computeBoardFitTransformFromBounds(
    bounds,
    viewWidth,
    viewHeight,
    padding,
    verticalAlign,
    maxUpscale,
  );
}

export function logBoardFit(payload: BoardFitLogPayload): void {
  if (!instructionLifecycleDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[BOARD_FIT] ${JSON.stringify(payload)}`);
}

/** Parse translate/scale from fit transform for diagnostics. */
export function parseBoardFitTransform(transform: string | null): {
  scale: number;
  translate: { tx: number; ty: number };
} | null {
  if (!transform) return null;
  const m = transform.match(
    /translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([-\d.]+)\)/,
  );
  if (!m) return null;
  return { translate: { tx: Number(m[1]), ty: Number(m[2]) }, scale: Number(m[3]) };
}

export type BoardDisplayFrame = {
  viewBox: string;
  width: number;
  height: number;
  frameY: number;
  frameH: number;
};

/**
 * Crop the placement canvas to transformed ink.
 * The fit scale and translate stay the ones computed for the full canvas.
 */
export function boardDisplayFrame(args: {
  width: number;
  ink: ContentBounds;
  fit: { scale: number; translate: { tx: number; ty: number } };
  pad?: number;
}): BoardDisplayFrame {
  const pad = args.pad ?? BOARD_DISPLAY_PAD;
  const { scale, translate } = args.fit;
  const top = translate.ty + args.ink.minY * scale;
  const bottom = translate.ty + args.ink.maxY * scale;
  const frameY = Math.max(0, top - pad);
  const frameH = Math.max(1, bottom + pad - frameY);
  return {
    width: args.width,
    height: frameH,
    frameY,
    frameH,
    viewBox: `0 ${frameY} ${args.width} ${frameH}`,
  };
}
