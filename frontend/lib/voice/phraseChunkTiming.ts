/**
 * Map Lemonfox word timestamps onto pedagogical chunk indices
 * (word-count accumulation shared with playback-progress sync).
 */

export type WordTimestampLike = {
  word: string;
  start: number;
  end: number;
};

export function mapTimestampsToChunkReveals(
  timestamps: WordTimestampLike[],
  chunks: string[],
): { chunkIndex: number; delayMs: number }[] {
  if (!timestamps.length || !chunks.length) return [];

  const chunkWordCounts = chunks.map((c) => c.split(/\s+/).filter(Boolean).length);
  const chunkWordEnds: number[] = [];
  chunkWordCounts.reduce((acc, n, i) => {
    chunkWordEnds[i] = acc + n;
    return acc + n;
  }, 0);

  const reveals: { chunkIndex: number; delayMs: number }[] = [];
  const seen = new Set<number>();

  timestamps.forEach((stamp, wordIdx) => {
    const chunkIdx = chunkWordEnds.findIndex((end) => wordIdx < end);
    if (chunkIdx < 0 || seen.has(chunkIdx)) return;
    seen.add(chunkIdx);
    const delayMs = Math.max(0, Math.round((stamp.start || 0) * 1000));
    reveals.push({ chunkIndex: chunkIdx, delayMs });
  });

  return reveals;
}

/** Cumulative word ends per chunk — used for playback-progress sync. */
export function chunkWordEndOffsets(chunks: string[]): number[] {
  const ends: number[] = [];
  chunks
    .map((c) => c.split(/\s+/).filter(Boolean).length)
    .reduce((acc, n, i) => {
      ends[i] = acc + n;
      return acc + n;
    }, 0);
  return ends;
}

/**
 * Map playback fraction [0,1] onto a chunk index using word-weighted spans
 * (longer chunks occupy more of the audio timeline).
 */
export function chunkIndexForPlaybackProgress(
  progress01: number,
  chunkWordEnds: number[],
): number {
  if (!chunkWordEnds.length) return 0;
  const totalWords = chunkWordEnds[chunkWordEnds.length - 1] || 1;
  const p = Math.min(1, Math.max(0, progress01));
  const wordIdx = Math.min(totalWords - 1, Math.floor(p * totalWords));
  const idx = chunkWordEnds.findIndex((end) => wordIdx < end);
  return idx >= 0 ? idx : chunkWordEnds.length - 1;
}
