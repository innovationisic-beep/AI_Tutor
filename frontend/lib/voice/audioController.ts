/**
 * Single shared HTMLAudioElement controller for Lemonfox-backed TTS.
 * Preserves the voice.ts speak contract: start / chunk reveal / end / cancel.
 *
 * Production path: progressive stream session → HTMLAudioElement progressive MP3.
 */

import { prepareSpeechStream } from "@/lib/api";
import {
  chunkIndexForPlaybackProgress,
  chunkWordEndOffsets,
} from "@/lib/voice/phraseChunkTiming";
import { logTtsTiming, nowMs } from "@/lib/voice/ttsTiming";

const TOKEN_KEY = "ai_tutor_token";

export type PhraseChunkSyncHooks = {
  onUtteranceStart?: () => void;
  onChunkReveal?: (event: { chunkIndex: number; atMs: number }) => void;
  onUtteranceEnd?: () => void;
};

type SpeakOptions = {
  text: string;
  hooks?: PhraseChunkSyncHooks;
  chunks?: string[];
};

let audioEl: HTMLAudioElement | null = null;
let generation = 0;
let abortController: AbortController | null = null;
let chunkTimerIds: ReturnType<typeof setTimeout>[] = [];
let playbackSyncCleanup: (() => void) | null = null;
let audioUnlocked = false;
/** Once-guarded finish for the active utterance (cancel must resolve awaiters). */
let activeFinish: (() => void) | null = null;
/** Web Audio boost path (only when gain > 1); MediaElementSource attaches once. */
let playbackAudioCtx: AudioContext | null = null;
let playbackGainNode: GainNode | null = null;
let playbackMediaSourceAttached = false;

/**
 * Separate from Lemonfox tone (voice/speed). Default 1.0 = no change.
 * Values ≤1 use HTMLAudioElement.volume; >1 uses GainNode (cap 1.25).
 * Override with NEXT_PUBLIC_TTS_PLAYBACK_GAIN (e.g. 1.15 after a listen pass).
 */
function getPlaybackGain(): number {
  const raw = process.env.NEXT_PUBLIC_TTS_PLAYBACK_GAIN;
  const n = raw === undefined || raw === "" ? 1.0 : Number(raw);
  if (!Number.isFinite(n) || n < 0) return 1.0;
  return Math.min(1.25, n);
}

function applyPlaybackLoudness(el: HTMLAudioElement): void {
  const gain = getPlaybackGain();
  if (gain <= 1) {
    el.volume = gain;
    if (playbackGainNode) playbackGainNode.gain.value = 1;
    return;
  }

  el.volume = 1;
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    if (!playbackAudioCtx) playbackAudioCtx = new Ctx();
    if (!playbackMediaSourceAttached) {
      const src = playbackAudioCtx.createMediaElementSource(el);
      playbackGainNode = playbackAudioCtx.createGain();
      src.connect(playbackGainNode);
      playbackGainNode.connect(playbackAudioCtx.destination);
      playbackMediaSourceAttached = true;
    }
    if (playbackGainNode) playbackGainNode.gain.value = gain;
    if (playbackAudioCtx.state === "suspended") {
      void playbackAudioCtx.resume();
    }
  } catch {
    el.volume = 1;
  }
}

function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function getAudioElement(): HTMLAudioElement {
  if (!audioEl) {
    audioEl = new Audio();
    audioEl.preload = "auto";
  }
  applyPlaybackLoudness(audioEl);
  return audioEl;
}

function clearChunkTimers(): void {
  chunkTimerIds.forEach(clearTimeout);
  chunkTimerIds = [];
  if (playbackSyncCleanup) {
    playbackSyncCleanup();
    playbackSyncCleanup = null;
  }
}

function stopAudioElement(): void {
  const el = audioEl;
  if (!el) return;
  try {
    el.onplaying = null;
    el.onended = null;
    el.onerror = null;
    el.ontimeupdate = null;
    el.onloadedmetadata = null;
    el.pause();
    el.removeAttribute("src");
    el.load();
  } catch {
    /* ignore */
  }
}

function resolveActiveFinish(): void {
  const fn = activeFinish;
  activeFinish = null;
  fn?.();
}

/** Cancel any in-flight synthesis/playback. Awaiters resolve via their once-guards. */
export function cancelSpeech(): void {
  generation += 1;
  clearChunkTimers();
  if (abortController) {
    try {
      abortController.abort();
    } catch {
      /* ignore */
    }
    abortController = null;
  }
  stopAudioElement();
  resolveActiveFinish();
}

/**
 * Unlock HTML audio after a user gesture (session start / continue click).
 * Safe to call repeatedly; no-op if already unlocked or SSR.
 */
export function unlockAudioPlayback(): void {
  if (typeof window === "undefined" || audioUnlocked) return;
  try {
    const el = getAudioElement();
    const silent =
      "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";
    el.src = silent;
    el.muted = true;
    const p = el.play();
    const done = () => {
      el.pause();
      el.muted = false;
      el.removeAttribute("src");
      el.load();
      audioUnlocked = true;
    };
    if (p && typeof p.then === "function") {
      void p.then(done).catch(() => {
        el.muted = false;
        audioUnlocked = true;
      });
    } else {
      done();
    }
  } catch {
    audioUnlocked = true;
  }
}

/**
 * Dev/test convenience: NEXT_PUBLIC_TTS_ENABLED=false bypasses Lemonfox.
 * Default ON when unset so production stays spoken if the var is omitted.
 * Requires a Next.js frontend restart after changing.
 */
export function isTtsFeatureEnabled(): boolean {
  return process.env.NEXT_PUBLIC_TTS_ENABLED !== "false";
}

export function isTtsClientAvailable(): boolean {
  if (!isTtsFeatureEnabled()) return false;
  if (typeof window === "undefined") return false;
  if (typeof Audio === "undefined") return false;
  return Boolean(getAuthToken());
}

/** Soft-fail: start → reveal-all chunks → end (no audio / no provider). */
function softFailUtterance(
  hooks: PhraseChunkSyncHooks,
  chunks: string[],
  finish: () => void,
): void {
  const { onUtteranceStart, onChunkReveal } = hooks;
  onUtteranceStart?.();
  chunks.forEach((_, i) => onChunkReveal?.({ chunkIndex: i, atMs: 0 }));
  finish();
}

export { mapTimestampsToChunkReveals } from "@/lib/voice/phraseChunkTiming";

/**
 * Sync phrase chunks to real HTMLAudioElement playback progress.
 * Word-weighted mapping without Lemonfox word_timestamps latency.
 */
function bindPlaybackProgressChunkSync(
  el: HTMLAudioElement,
  chunks: string[],
  onChunkReveal: PhraseChunkSyncHooks["onChunkReveal"],
  myGen: number,
): void {
  if (!chunks.length || !onChunkReveal) return;

  clearChunkTimers();

  const chunkWordEnds = chunkWordEndOffsets(chunks);
  let lastRevealed = -1;

  const revealUpTo = (chunkIdx: number) => {
    if (myGen !== generation) return;
    const capped = Math.min(chunkIdx, chunks.length - 1);
    for (let i = lastRevealed + 1; i <= capped; i++) {
      onChunkReveal({ chunkIndex: i, atMs: Date.now() });
    }
    lastRevealed = Math.max(lastRevealed, capped);
  };

  const tick = () => {
    if (myGen !== generation) return;
    const duration = el.duration;
    if (!Number.isFinite(duration) || duration <= 0) return;
    const progress = Math.min(1, Math.max(0, el.currentTime / duration));
    const chunkIdx = chunkIndexForPlaybackProgress(progress, chunkWordEnds);
    if (chunkIdx > lastRevealed) revealUpTo(chunkIdx);
  };

  const onEndedReveal = () => {
    if (myGen !== generation) return;
    revealUpTo(chunks.length - 1);
  };

  el.ontimeupdate = tick;
  el.onloadedmetadata = tick;
  el.addEventListener("ended", onEndedReveal);
  tick();

  playbackSyncCleanup = () => {
    if (el.ontimeupdate === tick) el.ontimeupdate = null;
    if (el.onloadedmetadata === tick) el.onloadedmetadata = null;
    el.removeEventListener("ended", onEndedReveal);
  };
}

/** Last-resort estimate when audio.duration is unavailable. */
function scheduleTimerFallback(
  cleaned: string,
  chunks: string[],
  onChunkReveal: PhraseChunkSyncHooks["onChunkReveal"],
): void {
  if (!chunks.length || !onChunkReveal) return;
  const wordCount = cleaned.split(/\s+/).filter(Boolean).length;
  // Lemonfox ~sarah pacing estimate when duration is unknown yet (~280ms/word).
  const estimatedDurationMs = Math.max(400, wordCount * 280);
  const interval = estimatedDurationMs / chunks.length;
  chunks.forEach((_, i) => {
    const id = setTimeout(() => {
      onChunkReveal({ chunkIndex: i, atMs: Date.now() });
    }, Math.round(interval * i));
    chunkTimerIds.push(id);
  });
}

/** Bind progress sync once duration is known; else wait briefly then timer-fallback. */
function startChunkSyncForPlayback(
  el: HTMLAudioElement,
  cleaned: string,
  chunks: string[],
  onChunkReveal: PhraseChunkSyncHooks["onChunkReveal"],
  myGen: number,
): void {
  if (!chunks.length || !onChunkReveal) return;

  const tryBind = (): boolean => {
    if (myGen !== generation) return true;
    const duration = el.duration;
    if (Number.isFinite(duration) && duration > 0) {
      bindPlaybackProgressChunkSync(el, chunks, onChunkReveal, myGen);
      return true;
    }
    return false;
  };

  if (tryBind()) return;

  const onMeta = () => {
    if (tryBind()) {
      el.removeEventListener("loadedmetadata", onMeta);
      el.removeEventListener("durationchange", onMeta);
    }
  };
  el.addEventListener("loadedmetadata", onMeta);
  el.addEventListener("durationchange", onMeta);

  const fallbackId = setTimeout(() => {
    if (myGen !== generation) return;
    if (tryBind()) return;
    el.removeEventListener("loadedmetadata", onMeta);
    el.removeEventListener("durationchange", onMeta);
    scheduleTimerFallback(cleaned, chunks, onChunkReveal);
  }, 1200);
  chunkTimerIds.push(fallbackId);

  playbackSyncCleanup = () => {
    el.removeEventListener("loadedmetadata", onMeta);
    el.removeEventListener("durationchange", onMeta);
  };
}

/**
 * Speak one utterance via progressive Lemonfox stream + single HTMLAudioElement.
 * Resolves on end, error, cancel, or soft-failure (never hangs callers).
 */
export function speakViaGateway(options: SpeakOptions): Promise<void> {
  const { text, hooks = {}, chunks = [] } = options;
  const { onUtteranceStart, onChunkReveal, onUtteranceEnd } = hooks;

  return new Promise<void>((resolve) => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      if (activeFinish === finish) activeFinish = null;
      clearChunkTimers();
      onUtteranceEnd?.();
      resolve();
    };

    if (typeof window === "undefined") {
      softFailUtterance(hooks, chunks, finish);
      return;
    }

    const cleaned = text.trim();
    if (!cleaned) {
      softFailUtterance(hooks, chunks, finish);
      return;
    }

    // Feature flag / client gate — before prepareSpeechStream (zero Lemonfox cost).
    const token = getAuthToken();
    if (!isTtsFeatureEnabled() || !token || typeof Audio === "undefined") {
      softFailUtterance(hooks, chunks, finish);
      return;
    }

    cancelSpeech();
    const myGen = generation;
    const ac = new AbortController();
    abortController = ac;
    activeFinish = finish;

    const tRequested = nowMs();
    logTtsTiming("tts.requested_at", {
      gen_id: myGen,
      text_chars: cleaned.length,
      progressive: true,
    });

    void (async () => {
      try {
        await speakProgressiveStream({
          token,
          cleaned,
          chunks,
          hooks: { onUtteranceStart, onChunkReveal },
          myGen,
          ac,
          tRequested,
          finish,
        });
      } catch {
        if (ac.signal.aborted || myGen !== generation) {
          finish();
          return;
        }
        softFailUtterance(hooks, chunks, finish);
      }
    })();
  });
}

type InternalSpeakCtx = {
  token: string;
  cleaned: string;
  chunks: string[];
  hooks: {
    onUtteranceStart?: () => void;
    onChunkReveal?: PhraseChunkSyncHooks["onChunkReveal"];
  };
  myGen: number;
  ac: AbortController;
  tRequested: number;
  finish: () => void;
};

async function speakProgressiveStream(ctx: InternalSpeakCtx): Promise<void> {
  const { token, cleaned, chunks, hooks, myGen, ac, tRequested, finish } = ctx;
  const { onUtteranceStart, onChunkReveal } = hooks;

  const tPrepare = nowMs();
  logTtsTiming("tts.fe_prepare_start", {
    gen_id: myGen,
    text_chars: cleaned.length,
    progressive: true,
  });

  const playSession = async (
    streamUrl: string,
    textChars: number,
  ): Promise<"ended" | "error" | "cancelled"> => {
    if (myGen !== generation) return "cancelled";
    const el = getAudioElement();
    return new Promise((resolve) => {
      let settled = false;
      const settle = (outcome: "ended" | "error" | "cancelled") => {
        if (settled) return;
        settled = true;
        resolve(outcome);
      };
      el.onplaying = () => {
        if (myGen !== generation) {
          settle("cancelled");
          return;
        }
        logTtsTiming("tts.playing", {
          gen_id: myGen,
          text_chars: textChars,
          progressive: true,
          since_requested_ms: Math.round(nowMs() - tRequested),
        });
        onUtteranceStart?.();
        if (chunks.length && onChunkReveal) {
          startChunkSyncForPlayback(el, cleaned, chunks, onChunkReveal, myGen);
        }
      };
      el.onended = () => settle("ended");
      el.onerror = () => settle("error");
      // Do not set currentTime here. The ticket URL is single-use, and a seek
      // aborts the first GET so the element errors before any audio plays.
      el.src = streamUrl;
      logTtsTiming("tts.play_called", {
        gen_id: myGen,
        progressive: true,
        since_requested_ms: Math.round(nowMs() - tRequested),
      });
      const playPromise = el.play();
      if (playPromise && typeof playPromise.then === "function") {
        playPromise.catch(() => settle("error"));
      }
    });
  };

  const session = await prepareSpeechStream(token, cleaned, { signal: ac.signal });
  if (myGen !== generation) {
    finish();
    return;
  }

  logTtsTiming("tts.fe_prepare_done", {
    gen_id: myGen,
    text_chars: session.textChars,
    progressive: true,
    prepare_ms: Math.round(nowMs() - tPrepare),
    since_requested_ms: Math.round(nowMs() - tRequested),
  });

  let outcome = await playSession(session.streamUrl, session.textChars);
  if (outcome === "error" && myGen === generation && !ac.signal.aborted) {
    logTtsTiming("tts.retry", {
      gen_id: myGen,
      text_chars: cleaned.length,
      progressive: true,
    });
    const retry = await prepareSpeechStream(token, cleaned, { signal: ac.signal });
    if (myGen !== generation) {
      finish();
      return;
    }
    outcome = await playSession(retry.streamUrl, retry.textChars);
  }

  if (myGen !== generation) {
    finish();
    return;
  }
  if (outcome === "ended") {
    finish();
    return;
  }
  if (outcome === "error") {
    onUtteranceStart?.();
    chunks.forEach((_, i) => onChunkReveal?.({ chunkIndex: i, atMs: 0 }));
    finish();
  }
}
