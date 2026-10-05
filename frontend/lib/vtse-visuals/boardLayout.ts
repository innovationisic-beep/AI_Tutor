/**
 * Width choice for the whiteboard scroll column.
 * Only a primary VTSE timeline that actually has a visual package opts out
 * of the centered max-w-6xl column. Every other item keeps that column.
 */

export const WHITEBOARD_CONTENT_COLUMN_CLASS = "mx-auto w-full max-w-6xl";

/**
 * Full scrollport width. The scroll surface already insets the right edge
 * (pr-6 / md:pr-10). The extra left padding balances that gutter to ~24–40px
 * without negative margins.
 */
export const VTSE_VISUAL_WIDE_CLASS = "w-full min-w-0 pl-5 pr-0 md:pl-6 md:pr-0";

/** Side-by-side only when the VTSE item itself is at least this wide. */
export const VTSE_VISUAL_SPLIT_MIN_PX = 1120;

/** Left board share of the wide item once the split is active. */
export const VTSE_VISUAL_BOARD_PERCENT = 70;

/** Right image share of the wide item once the split is active. */
export const VTSE_VISUAL_PANE_PERCENT = 30;

type TimelineLike = {
  metadata?: Record<string, unknown> | null;
} | null | undefined;

export function timelineHasVtseVisualPackage(timeline: TimelineLike): boolean {
  const pkg = timeline?.metadata?.vtse_visual_package as
    | { images?: unknown[] }
    | null
    | undefined;
  return Array.isArray(pkg?.images) && pkg.images.length > 0;
}

export type VtseVisualWidthMode = "column" | "wide";

/** Item-level width. Independent of FlowCheckpoint and of later stages. */
export function vtseVisualWidthMode(opts: {
  hasPackage: boolean;
  showVisuals: boolean;
}): VtseVisualWidthMode {
  if (!opts.hasPackage || !opts.showVisuals) return "column";
  return "wide";
}

export type VtseVisualFlowMode = "board" | "split" | "stack";

/**
 * Inside a wide VTSE item: split at desktop container width, stack below it.
 * `board` is the unchanged single-diagram path (no package, reteach, or a
 * failed image).
 */
export function vtseVisualFlowMode(opts: {
  hasPackage: boolean;
  showVisuals: boolean;
  containerWidth: number;
  imageUnavailable?: boolean;
}): VtseVisualFlowMode {
  if (!opts.hasPackage || !opts.showVisuals || opts.imageUnavailable) return "board";
  if (opts.containerWidth < VTSE_VISUAL_SPLIT_MIN_PX) return "stack";
  return "split";
}
