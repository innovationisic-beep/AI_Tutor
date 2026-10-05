"use client";

import { useEffect, useRef, useState } from "react";
import { WhiteboardWritingMarker } from "@/components/ai/WhiteboardWritingMarker";
import {
  boardInkForSpeechProgress,
  completedSentenceIndexForSpeechProgress,
  visibleTextForNarrationProgress,
  type BoardWrite,
} from "@/lib/instruction-timeline-v3/teaching/pedagogicalPhraseChunks";
import {
  advanceSpeechRevealForNarrationChunk,
  createSpeechRevealState,
  resolveSpeechDisplayText,
  stabilizeSpeechReveal,
  type SpeechRevealState,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";
import { wordChunks } from "@/lib/instruction-timeline-v3/teaching/pedagogicalWordChunks";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import { cleanTextForSpeech, speakWithPhraseChunkSync, cancelSpeech } from "@/lib/voice";
import { cn } from "@/lib/utils";

export type BoardWriteProp = BoardWrite;

type Props = {
  /** Spoken string — TTS source. Keep stable across rerenders. */
  text: string;
  /**
   * Optional visible writing that differs from speech.
   * - undefined: reveal spoken `text` (legacy / default)
   * - "": speak only; write nothing
   * - non-empty: reveal this string in sync with narration progress
   * Ignored for live reveal when `boardWrites` is non-empty.
   */
  displayText?: string;
  /**
   * Sentence-anchored board writes. When non-empty, ink reveals by spoken
   * sentence completion (validated sentenceIndex). Prefer over displayText.
   */
  boardWrites?: BoardWrite[];
  className?: string;
  /** Called once when all words are displayed and TTS finishes. */
  onComplete?: () => void;
  /**
   * Fires when spoken sentence progress advances (0-based completed index).
   * Used by Visual Teaching to apply sentence_events patches.
   */
  onSentenceProgress?: (sentenceIndex: number) => void;
  /** Resume mode: show full text immediately, no TTS or animation. */
  staticMode?: boolean;
  /**
   * Initial completed sentence index for mid-beat restore (-1 = beat start).
   * Board ink and sentence progress start from this cursor.
   */
  initialSentenceIndex?: number;
};

function joinBoardWrites(writes: readonly BoardWrite[]): string {
  return writes
    .filter((w) => String(w.text || "").trim())
    .sort((a, b) => a.sentenceIndex - b.sentenceIndex)
    .map((w) => w.text.trim())
    .join("\n");
}

/**
 * Zone 0 / legacy whiteboard prose — word-by-word reveal synced to TTS.
 * When `boardWrites` is set, reveal is sentence-anchored.
 * Else when `displayText` is set, TTS still speaks `text` but the visible ink
 * uses proportional `displayText` mapping (legacy).
 */
export function WordSyncedStreaming({
  text,
  displayText,
  boardWrites,
  className,
  onComplete,
  onSentenceProgress,
  staticMode = false,
  initialSentenceIndex = -1,
}: Props) {
  const [reveal, setReveal] = useState<SpeechRevealState | null>(null);
  const [isDone, setIsDone] = useState(true);
  /** Progress-mapped visible writing when display differs from speech. */
  const [mappedVisible, setMappedVisible] = useState<string | null>(null);

  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

  const onSentenceProgressRef = useRef(onSentenceProgress);
  useEffect(() => {
    onSentenceProgressRef.current = onSentenceProgress;
  });

  const displayTextRef = useRef(displayText);
  useEffect(() => {
    displayTextRef.current = displayText;
  });

  const boardWritesRef = useRef(boardWrites);
  useEffect(() => {
    boardWritesRef.current = boardWrites;
  });

  const runIdRef = useRef(0);
  const lastSentenceRef = useRef(-1);

  useEffect(() => {
    const writes = boardWritesRef.current ?? [];
    const useWrites = writes.length > 0;
    const dualDisplay = useWrites || displayText !== undefined;
    const writesFull = useWrites ? joinBoardWrites(writes) : "";
    const displayFull = useWrites
      ? writesFull
      : dualDisplay
        ? cleanTextForSpeech(displayText ?? "")
        : cleanTextForSpeech(text);

    const seedSentence = Number.isFinite(initialSentenceIndex)
      ? Math.floor(initialSentenceIndex)
      : -1;
    lastSentenceRef.current = seedSentence;

    if (staticMode) {
      const speakFull = cleanTextForSpeech(text);
      const entityId = `wb-static-${runIdRef.current}`;
      const revealSource = dualDisplay ? displayFull : speakFull;
      const state = stabilizeSpeechReveal(
        createSpeechRevealState(entityId, revealSource || "\u00a0"),
        Date.now(),
      );
      setReveal({ ...state });
      setMappedVisible(dualDisplay ? displayFull : null);
      setIsDone(true);
      const sentences = speakFull
        ? speakFull.split(/(?<=[.?!])\s+/).filter(Boolean)
        : [];
      if (sentences.length > 0) {
        onSentenceProgressRef.current?.(sentences.length - 1);
      }
      return;
    }

    runIdRef.current += 1;
    const myRunId = runIdRef.current;
    let cancelled = false;

    const fullText = cleanTextForSpeech(text);
    const chunks = wordChunks(fullText);
    const entityId = `wb-${myRunId}`;
    // Reveal state tracks spoken chunks for sync; visible ink may use writes/displayText.
    let state = createSpeechRevealState(entityId, fullText || "\u00a0");
    setReveal({ ...state });
    // Seed board ink from restored sentence cursor when present.
    if (useWrites && seedSentence >= 0) {
      const seeded = writes
        .filter((w) => w.sentenceIndex <= seedSentence)
        .sort((a, b) => a.sentenceIndex - b.sentenceIndex)
        .map((w) => w.text.trim())
        .filter(Boolean)
        .join("\n");
      setMappedVisible(seeded);
    } else {
      setMappedVisible(dualDisplay ? "" : null);
    }
    setIsDone(false);

    if (seedSentence >= 0) {
      onSentenceProgressRef.current?.(seedSentence);
    }

    if (!fullText) {
      setMappedVisible(dualDisplay ? displayFull : null);
      setIsDone(true);
      onCompleteRef.current?.();
      return;
    }

    const patchReveal = (next: SpeechRevealState) => {
      state = next;
      setReveal({ ...next });
    };

    const emitSentenceProgress = (chunkIndex: number) => {
      const completed = completedSentenceIndexForSpeechProgress(
        fullText,
        chunkIndex,
        chunks.length,
      );
      if (completed > lastSentenceRef.current) {
        lastSentenceRef.current = completed;
        onSentenceProgressRef.current?.(completed);
      }
    };

    const syncMappedVisible = (chunkIndex: number) => {
      if (!dualDisplay) {
        setMappedVisible(null);
        return;
      }
      const liveWrites = boardWritesRef.current ?? [];
      if (liveWrites.length > 0) {
        setMappedVisible(
          boardInkForSpeechProgress(
            fullText,
            liveWrites,
            chunkIndex,
            chunks.length,
          ),
        );
        return;
      }
      const note = cleanTextForSpeech(displayTextRef.current ?? "");
      if (!note) {
        setMappedVisible("");
        return;
      }
      setMappedVisible(
        visibleTextForNarrationProgress(note, chunkIndex, chunks.length),
      );
    };

    const finish = () => {
      if (cancelled || runIdRef.current !== myRunId) return;
      patchReveal(stabilizeSpeechReveal(state, Date.now()));
      if (dualDisplay) {
        const liveWrites = boardWritesRef.current ?? [];
        if (liveWrites.length > 0) {
          setMappedVisible(joinBoardWrites(liveWrites));
        } else {
          setMappedVisible(cleanTextForSpeech(displayTextRef.current ?? ""));
        }
      }
      emitSentenceProgress(chunks.length - 1);
      setIsDone(true);
      onCompleteRef.current?.();
    };

    // Always use speakWithPhraseChunkSync: when TTS is disabled/unavailable it
    // soft-fails with reveal-all + immediate onUtteranceEnd (no typing delay).
    void speakWithPhraseChunkSync(
      fullText,
      {
        onUtteranceStart: () => {
          if (cancelled || runIdRef.current !== myRunId) return;
          patchReveal(
            advanceSpeechRevealForNarrationChunk(
              state,
              0,
              chunks.length,
              Date.now(),
            ),
          );
          syncMappedVisible(0);
          emitSentenceProgress(0);
        },
        onChunkReveal: ({ chunkIndex, atMs }) => {
          if (cancelled || runIdRef.current !== myRunId) return;
          patchReveal(
            advanceSpeechRevealForNarrationChunk(
              state,
              chunkIndex,
              chunks.length,
              atMs,
            ),
          );
          syncMappedVisible(chunkIndex);
          emitSentenceProgress(chunkIndex);
        },
        onUtteranceEnd: () => {
          finish();
        },
      },
      chunks,
    );

    return () => {
      cancelled = true;
      cancelSpeech();
    };
    // displayText / boardWrites intentionally omitted — changing writing must not restart TTS.
  }, [text, staticMode, initialSentenceIndex]);

  const writes = boardWrites ?? [];
  const useWrites = writes.length > 0;
  const dualDisplay = useWrites || displayText !== undefined;
  const speakFull = cleanTextForSpeech(text);
  const displayFull = useWrites
    ? joinBoardWrites(writes)
    : dualDisplay
      ? cleanTextForSpeech(displayText ?? "")
      : speakFull;

  // Speak-only / zero-ink: TTS effect still runs; no layout for empty board writing.
  if (dualDisplay && !displayFull.trim()) {
    return null;
  }

  const revealSource = dualDisplay
    ? mappedVisible ?? (staticMode || isDone ? displayFull : "")
    : speakFull;

  // Pre-first-write (boardWrites pending): avoid empty <p> line-height gap.
  if (dualDisplay && !String(revealSource).trim()) {
    return null;
  }

  const pendingReveal =
    revealSource && !reveal
      ? createSpeechRevealState("wb-pending", revealSource)
      : undefined;

  const speech = dualDisplay
    ? {
        phase: (isDone ? "stable" : "speaking") as "stable" | "speaking",
        visibleText: revealSource,
        passivePrefix: revealSource,
        activeSuffix: "",
      }
    : resolveSpeechDisplayText(
        speakFull,
        reveal ?? pendingReveal,
        Boolean(speakFull),
      );

  const showMarker =
    !isDone &&
    speech.phase === "speaking" &&
    Boolean(speech.visibleText.trim());

  if (!speakFull && !text.trim() && !displayFull.trim()) {
    return null;
  }

  const passiveMuted =
    speech.phase === "speaking" && Boolean(speech.activeSuffix);

  return (
    <p
      className={cn(
        WHITEBOARD_TEXT_CLASS,
        "relative whitespace-pre-wrap",
        className,
      )}
    >
      {speech.passivePrefix ? (
        <span className={passiveMuted ? "opacity-[0.78]" : undefined}>
          {speech.passivePrefix}
        </span>
      ) : null}
      {speech.activeSuffix ? (
        <>
          {speech.passivePrefix ? " " : null}
          <span
            className={
              speech.phase === "speaking"
                ? "opacity-100 drop-shadow-[0_0_0.5px_rgba(79,70,229,0.35)]"
                : undefined
            }
          >
            {speech.activeSuffix}
          </span>
        </>
      ) : null}
      {!speech.passivePrefix && !speech.activeSuffix && speech.visibleText ? (
        <span>{speech.visibleText}</span>
      ) : null}
      {showMarker ? <WhiteboardWritingMarker /> : null}
    </p>
  );
}
