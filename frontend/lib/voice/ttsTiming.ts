/**
 * Lightweight TTS latency timing (T4–T11). Console-only; no behavior change.
 * Enable via localStorage ai_tutor_tts_debug=1 or NEXT_PUBLIC_TTS_DEBUG=1.
 */

export type TtsTimingFields = Record<string, string | number | boolean | null | undefined>;

function ttsDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (window.localStorage.getItem("ai_tutor_tts_debug") === "1") return true;
  } catch {
    /* ignore */
  }
  return process.env.NEXT_PUBLIC_TTS_DEBUG === "1";
}

/** Always log structured TTS timing when debug is on; otherwise no-op. */
export function logTtsTiming(event: string, fields: TtsTimingFields = {}): void {
  if (!ttsDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.info(`[tts.timing] ${event}`, {
    t_ms: typeof performance !== "undefined" ? Math.round(performance.now()) : Date.now(),
    ...fields,
  });
}

export function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}
