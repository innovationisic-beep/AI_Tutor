/**
 * Tutor speech surface — Lemonfox-backed via Voice Gateway.
 *
 * Public contract: speakUtteranceWithHooks / speakWithPhraseChunkSync resolve on
 * end or error (including cancel) so teaching awaits never hang.
 *
 * Transport: progressive Lemonfox stream (prepare session → HTMLAudioElement).
 * Phrase reveals use playback progress (word-weighted) with a timer fallback.
 */

import {
  cancelSpeech,
  isTtsClientAvailable,
  isTtsFeatureEnabled,
  speakViaGateway,
  unlockAudioPlayback,
  type PhraseChunkSyncHooks,
} from "@/lib/voice/audioController";

export {
  cancelSpeech,
  unlockAudioPlayback,
  isTtsClientAvailable,
  isTtsFeatureEnabled,
};
export type { PhraseChunkSyncHooks };

/** Resolve after `ms` milliseconds (used for teaching pacing delays). */
export function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

/**
 * Strip markdown-ish markers so TTS does not read asterisks, bullets, or backticks.
 */
export function cleanTextForSpeech(text: string): string {
  return text
    .replace(/\*\*/g, "")
    .replace(/\*/g, "")
    .replace(/^- /gm, "")
    .replace(/`/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export type SpeakUtteranceHooks = {
  /** Called once the utterance finishes (end or error). */
  onUtteranceEnd?: () => void;
};

/**
 * Speak `text` with optional lifecycle hooks.
 * Resolves when the utterance ends (or immediately when TTS is unavailable).
 */
export function speakUtteranceWithHooks(
  text: string,
  hooks: SpeakUtteranceHooks,
): Promise<void> {
  const cleaned = cleanTextForSpeech(text);
  if (!cleaned) {
    hooks.onUtteranceEnd?.();
    return Promise.resolve();
  }
  return speakViaGateway({
    text: cleaned,
    hooks: { onUtteranceEnd: hooks.onUtteranceEnd },
  });
}

/**
 * Speak `text` and fire per-chunk reveal events so visual phrase-sync can
 * progressively reveal board annotations in sync with narration.
 */
export function speakWithPhraseChunkSync(
  text: string,
  hooks: PhraseChunkSyncHooks,
  chunks: string[],
): Promise<void> {
  const { onUtteranceStart, onChunkReveal, onUtteranceEnd } = hooks;

  if (typeof window === "undefined" || !isTtsClientAvailable()) {
    onUtteranceStart?.();
    chunks.forEach((_, i) => onChunkReveal?.({ chunkIndex: i, atMs: 0 }));
    onUtteranceEnd?.();
    return Promise.resolve();
  }

  const cleaned = cleanTextForSpeech(text);
  if (!cleaned) {
    onUtteranceStart?.();
    chunks.forEach((_, i) => onChunkReveal?.({ chunkIndex: i, atMs: 0 }));
    onUtteranceEnd?.();
    return Promise.resolve();
  }

  return speakViaGateway({
    text: cleaned,
    hooks,
    chunks,
  });
}
