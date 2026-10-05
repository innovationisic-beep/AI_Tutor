import { wordChunks } from "@/lib/instruction-timeline-v3/teaching/pedagogicalWordChunks";
import {
  advanceSpeechRevealForNarrationChunk,
  buildSpeechRevealDebugMeta,
  createSpeechRevealState,
  stabilizeSpeechReveal,
  type SpeechRevealDebugMeta,
  type SpeechRevealState,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import { speakWithPhraseChunkSync } from "@/lib/voice";

/** Strip legacy "On the left/right:" intro — headers speak the label only. */
export function normalizeColumnIntroNarration(text: string): string {
  const m = text.trim().match(/^On the (left|right):\s*(.+?)\.?$/i);
  return m ? m[2].trim() : text.trim();
}

/** TTS speaks board copy (what the teacher writes), not a separate long narration script. */
export function boardTextForSpeechReveal(
  targetEntityIds: string[],
  map: SpeechRevealMap,
  fallbackNarration: string,
): string {
  const boardParts = targetEntityIds
    .map((id) => map[id]?.fullText?.trim())
    .filter((t): t is string => Boolean(t));
  if (boardParts.length > 0) {
    return boardParts.join(" ");
  }
  return fallbackNarration.trim();
}

export async function speakSegmentWithSpeechReveal(options: {
  narrationText: string;
  targetEntityIds: string[];
  getRevealMap: () => SpeechRevealMap;
  patchRevealMap: (updater: (prev: SpeechRevealMap) => SpeechRevealMap) => void;
  onDebug?: (meta: SpeechRevealDebugMeta) => void;
  /** Existing speech clock. Callers use it for VTSE region cues; it must not affect the utterance. */
  onWordIndex?: (wordIndex: number) => void;
}): Promise<void> {
  const { targetEntityIds, getRevealMap, patchRevealMap, onDebug } = options;
  const map = getRevealMap();
  const textToSpeak = boardTextForSpeechReveal(
    targetEntityIds,
    map,
    options.narrationText,
  );
  const chunks = wordChunks(textToSpeak);

  const stabilizeAll = (atMs: number) => {
    patchRevealMap((prev) => {
      const next = { ...prev };
      for (const entityId of targetEntityIds) {
        const existing = next[entityId];
        if (!existing) continue;
        next[entityId] = stabilizeSpeechReveal(existing, atMs);
      }
      return next;
    });
  };

  if (!chunks.length) {
    stabilizeAll(Date.now());
    return;
  }

  let utteranceStartMs: number | null = null;
  const allTimestamps: number[] = [];
  let lastActiveChunk: number | null = null;

  const syncTargets = (wordIndex: number, atMs: number) => {
    try {
      options.onWordIndex?.(wordIndex);
    } catch {
      /* A diagram cue must never interrupt speech or the board. */
    }
    lastActiveChunk = wordIndex;
    allTimestamps.push(atMs);
    patchRevealMap((prev) => {
      const next = { ...prev };
      for (const entityId of targetEntityIds) {
        const existing = next[entityId];
        if (!existing) continue;
        next[entityId] = advanceSpeechRevealForNarrationChunk(
          existing,
          wordIndex,
          chunks.length,
          atMs,
        );
      }
      return next;
    });
  };

  await speakWithPhraseChunkSync(
    textToSpeak,
    {
      onUtteranceStart: () => {
        utteranceStartMs = Date.now();
        syncTargets(0, Date.now());
      },
      onChunkReveal: ({ chunkIndex, atMs }) => {
        syncTargets(chunkIndex, atMs);
      },
      onUtteranceEnd: () => {
        const endMs = Date.now();
        stabilizeAll(endMs);
        onDebug?.(
          buildSpeechRevealDebugMeta(
            chunks,
            allTimestamps,
            lastActiveChunk,
            utteranceStartMs,
            endMs,
          ),
        );
      },
    },
    chunks,
  );
}

export function registerSpeechRevealTargets(
  prev: SpeechRevealMap,
  targets: { entityId: string; fullText: string }[],
  narrationStartChunk = 0,
): SpeechRevealMap {
  const next = { ...prev };
  for (const t of targets) {
    const existing = next[t.entityId];
    if (existing?.phase === "stable") continue;
    next[t.entityId] = createSpeechRevealState(t.entityId, t.fullText, narrationStartChunk);
  }
  return next;
}
