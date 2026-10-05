/**
 * Whiteboard near-bottom auto-follow (WhatsApp-style).
 * Pure helpers only — no pedagogy / TTS / sendMessage coupling.
 */

export const BOARD_NEAR_BOTTOM_PX = 140;

export type ScrollMetrics = {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
};

export function distanceFromBottom(el: ScrollMetrics): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

export function isNearBottom(
  el: ScrollMetrics,
  thresholdPx: number = BOARD_NEAR_BOTTOM_PX
): boolean {
  return distanceFromBottom(el) <= thresholdPx;
}

/** Update stick flag from a scroll event (user intent). */
export function stickAfterUserScroll(
  el: ScrollMetrics,
  thresholdPx: number = BOARD_NEAR_BOTTOM_PX
): boolean {
  return isNearBottom(el, thresholdPx);
}

export type BoardScrollFollowInput = {
  /** Stable timeline episode keys in order (conversation slots). */
  timelineKeys?: string[];
  /** Last durable / visible board item id. */
  lastBoardItemId?: string | null;
  /** "Tutor is thinking…" row visible at the bottom. */
  thinkingVisible?: boolean;
  /**
   * External stage/panel that opened below (Concept Check, Cluster Quiz, …).
   * Empty / null when none.
   */
  panelKey?: string | null;
};

/**
 * Stable follow key. Changes only when visible structure changes —
 * not on streaming token growth, silent acks, or meta-only updates.
 */
export function buildBoardScrollFollowKey(input: BoardScrollFollowInput): string {
  const keys = (input.timelineKeys ?? []).filter(Boolean);
  const lastBoard = String(input.lastBoardItemId ?? "").trim();
  const thinking = input.thinkingVisible ? "1" : "0";
  const panel = String(input.panelKey ?? "").trim();
  return [
    `tl:${keys.join(",")}`,
    `board:${lastBoard}`,
    `think:${thinking}`,
    `panel:${panel}`,
  ].join("|");
}

export function shouldScrollOnFollowKeyChange(opts: {
  enabled: boolean;
  stickToBottom: boolean;
  prevKey: string;
  nextKey: string;
}): boolean {
  if (!opts.enabled) return false;
  if (!opts.stickToBottom) return false;
  if (!opts.nextKey) return false;
  return opts.nextKey !== opts.prevKey;
}

/**
 * While the newest item streams/grows, keep following only if still stuck
 * near the bottom. Does not require a key change.
 */
export function shouldScrollOnContentGrowth(opts: {
  enabled: boolean;
  stickToBottom: boolean;
}): boolean {
  return opts.enabled && opts.stickToBottom;
}

export function scrollElementToBottom(
  el: { scrollTop: number; scrollHeight: number },
  behavior: ScrollBehavior = "smooth"
): void {
  const top = Math.max(0, el.scrollHeight);
  if (typeof (el as HTMLElement).scrollTo === "function") {
    (el as HTMLElement).scrollTo({ top, behavior });
    return;
  }
  el.scrollTop = top;
}
