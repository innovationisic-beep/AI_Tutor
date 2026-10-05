import { wordChunks } from "@/lib/instruction-timeline-v3/teaching/pedagogicalWordChunks";

export type VtseVisualCue = {
  char_start: number;
  asset_key: string;
  region_ids: string[];
};

export type VtseBeatVisual = {
  asset_key?: string;
  region_ids?: string[];
  image_path?: string;
  cues?: VtseVisualCue[];
  carry?: boolean;
};

/** Character offset of the word the speech clock is currently speaking. */
export function charOffsetForWord(text: string, wordIndex: number): number {
  if (!text || wordIndex <= 0) return 0;
  const chunks = wordChunks(text);
  let searchFrom = 0;
  const limit = Math.min(wordIndex, chunks.length - 1);
  for (let i = 0; i <= limit; i += 1) {
    const at = text.indexOf(chunks[i] ?? "", searchFrom);
    if (at < 0) return searchFrom;
    if (i === wordIndex) return at;
    searchFrom = at + (chunks[i]?.length ?? 0);
  }
  return searchFrom;
}

export function cueAtOffset(
  cues: VtseVisualCue[],
  charOffset: number
): VtseVisualCue | null {
  let chosen: VtseVisualCue | null = null;
  for (const cue of cues) {
    if (cue.char_start <= charOffset) chosen = cue;
  }
  return chosen;
}

export type VtseHighlightBeat = {
  beat_id?: string;
  narration_segments?: Array<{ text?: string }>;
  narration?: { segments?: Array<{ text?: string }> };
  metadata?: { vtse_visual?: VtseBeatVisual };
};

export type VtseHighlightImage = {
  asset_key?: string;
};

export type VtseHighlightFrame = {
  assetKey: string;
  regionIds: string[];
  cueIndex: number;
};

export function beatNarrationText(beat: VtseHighlightBeat | undefined): string {
  const segments = beat?.narration_segments;
  if (segments?.[0]?.text) return segments[0].text;
  return beat?.narration?.segments?.[0]?.text || "";
}

/**
 * Regions for the active beat. A cue that does not cover the current
 * narration offset keeps the previous cue. Regions clear only when the
 * active beat has no visual metadata and is not a carry beat.
 */
export function resolveVtseHighlight(args: {
  beats: VtseHighlightBeat[];
  images: VtseHighlightImage[];
  beatId: string | null;
  narrationWordIndex: number;
}): VtseHighlightFrame | null {
  const images = args.images.filter((img) => img.asset_key);
  if (!images.length) return null;
  const beats = args.beats;
  const index = args.beatId ? beats.findIndex((beat) => beat.beat_id === args.beatId) : -1;
  if (!args.beatId || index < 0) {
    const assetKey = images[0]?.asset_key || "";
    return assetKey ? { assetKey, regionIds: [], cueIndex: -1 } : null;
  }
  let assetKey = images[0]?.asset_key || "";
  let regionIds: string[] = [];
  let cueIndex = -1;
  for (let i = 0; i <= index; i += 1) {
    const visual = beats[i]?.metadata?.vtse_visual;
    if (visual?.carry) continue;
    if (!visual) {
      regionIds = [];
      cueIndex = -1;
      continue;
    }
    if (visual.asset_key) assetKey = visual.asset_key;
    const cues = visual.cues || [];
    if (i < index) {
      const last = cues[cues.length - 1];
      regionIds = last?.region_ids || visual.region_ids || [];
      cueIndex = cues.length ? cues.length - 1 : -1;
      if (last?.asset_key) assetKey = last.asset_key;
      continue;
    }
    if (!cues.length) {
      if (visual.region_ids?.length) {
        regionIds = [...visual.region_ids];
        cueIndex = -1;
      }
      continue;
    }
    const offset = charOffsetForWord(beatNarrationText(beats[i]), args.narrationWordIndex);
    const cue = cueAtOffset(cues, offset);
    if (!cue) continue;
    regionIds = [...(cue.region_ids || [])];
    cueIndex = cues.indexOf(cue);
    if (cue.asset_key) assetKey = cue.asset_key;
  }
  if (!assetKey) return null;
  return { assetKey, regionIds, cueIndex };
}

/** Narration-word steps spread across the beat's visible window. Index 0 is immediate. */
export function visualClockEvents(
  narrationText: string,
  visibleMs: number
): Array<{ atMs: number; narrationWordIndex: number }> {
  const count = Math.max(1, wordChunks(narrationText).length);
  const span = Math.max(0, visibleMs);
  return Array.from({ length: count }, (_, i) => ({
    atMs: count === 1 ? 0 : Math.round((span * i) / (count - 1)),
    narrationWordIndex: i,
  }));
}

export function narrationWordAtElapsed(
  events: Array<{ atMs: number; narrationWordIndex: number }>,
  elapsedMs: number
): number {
  let word = events[0]?.narrationWordIndex ?? 0;
  for (const event of events) {
    if (event.atMs <= elapsedMs) word = event.narrationWordIndex;
  }
  return word;
}

/** Map a board-speech word index onto the narration string the cues were stamped against. */
export function narrationWordIndexForBoardWord(
  narrationText: string,
  boardWordIndex: number,
  boardWordCount: number
): number {
  const narrCount = wordChunks(narrationText).length;
  if (narrCount <= 1) return 0;
  if (boardWordCount <= 1) return boardWordIndex <= 0 ? 0 : narrCount - 1;
  const progress = Math.min(1, Math.max(0, boardWordIndex / (boardWordCount - 1)));
  return Math.round(progress * (narrCount - 1));
}

/** True when every board word index arrived in one turn (TTS off or a soft-fail dump). */
export function isCollapsedWordBurst(indexes: number[], boardWordCount: number): boolean {
  if (boardWordCount <= 1 || indexes.length < 2) return false;
  return (
    indexes.length >= boardWordCount &&
    indexes[0] === 0 &&
    indexes[indexes.length - 1] >= boardWordCount - 1
  );
}
