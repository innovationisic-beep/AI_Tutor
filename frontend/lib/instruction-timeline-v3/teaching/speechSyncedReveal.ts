import type { RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import { joinPhraseChunks } from "@/lib/instruction-timeline-v3/teaching/pedagogicalPhraseChunks";
import {
  joinWordChunks,
  visibleTextForWordIndex,
  wordChunks,
} from "@/lib/instruction-timeline-v3/teaching/pedagogicalWordChunks";

export type SpeechRevealPhase = "pending" | "speaking" | "stable";

export type SpeechRevealState = {
  entityId: string;
  fullText: string;
  displayChunks: string[];
  visibleText: string;
  activeChunkIndex: number | null;
  phase: SpeechRevealPhase;
  chunkRevealTimestamps: number[];
  startedAtMs: number | null;
  /** When target appeared mid-narration (orchestrated during_segment). */
  narrationStartChunk: number;
};

export type SpeechRevealDebugMeta = {
  narration_chunk_count: number;
  chunk_reveal_timestamps: number[];
  active_speech_chunk: number | null;
  narration_sync_latency: number;
  reveal_completion_time: number | null;
};

export function createSpeechRevealState(
  entityId: string,
  fullText: string,
  narrationStartChunk = 0,
): SpeechRevealState {
  const displayChunks = wordChunks(fullText);
  return {
    entityId,
    fullText: fullText.trim(),
    displayChunks,
    visibleText: "",
    activeChunkIndex: null,
    phase: "pending",
    chunkRevealTimestamps: [],
    startedAtMs: null,
    narrationStartChunk,
  };
}

function resolveVisibleTextForTarget(
  state: SpeechRevealState,
  wordIndex: number,
  wordCount: number,
): string {
  if (wordIndex < state.narrationStartChunk) return "";
  if (state.narrationStartChunk > 0) {
    const span = wordCount - state.narrationStartChunk;
    const localIndex = wordIndex - state.narrationStartChunk;
    return visibleTextForWordIndex(
      state.fullText,
      Math.min(
        wordChunks(state.fullText).length - 1,
        Math.max(0, Math.round((localIndex / Math.max(1, span)) * wordChunks(state.fullText).length)),
      ),
    );
  }
  return visibleTextForWordIndex(state.fullText, wordIndex);
}

export function advanceSpeechRevealForNarrationChunk(
  state: SpeechRevealState,
  narrationChunkIndex: number,
  narrationChunkCount: number,
  atMs: number,
): SpeechRevealState {
  const visibleText = resolveVisibleTextForTarget(state, narrationChunkIndex, narrationChunkCount);
  const words = wordChunks(state.fullText);
  const displayIdx = Math.min(
    words.length - 1,
    Math.max(0, narrationChunkIndex - state.narrationStartChunk),
  );
  return {
    ...state,
    visibleText,
    activeChunkIndex: displayIdx,
    phase: "speaking",
    startedAtMs: state.startedAtMs ?? atMs,
    chunkRevealTimestamps: [...state.chunkRevealTimestamps, atMs],
  };
}

export function stabilizeSpeechReveal(state: SpeechRevealState, atMs: number): SpeechRevealState {
  return {
    ...state,
    visibleText: state.fullText,
    activeChunkIndex: null,
    phase: "stable",
    chunkRevealTimestamps: state.chunkRevealTimestamps.includes(atMs)
      ? state.chunkRevealTimestamps
      : [...state.chunkRevealTimestamps, atMs],
  };
}

export function resolveSpeechDisplayText(
  fullText: string,
  reveal: SpeechRevealState | undefined,
  speechRevealEnabled: boolean,
): {
  visibleText: string;
  activeChunkIndex: number | null;
  phase: SpeechRevealPhase | null;
  passivePrefix: string;
  activeSuffix: string;
} {
  if (!speechRevealEnabled || !reveal || reveal.phase === "stable") {
    return {
      visibleText: fullText,
      activeChunkIndex: null,
      phase: reveal?.phase ?? null,
      passivePrefix: fullText,
      activeSuffix: "",
    };
  }
  if (reveal.phase === "pending" && !reveal.visibleText) {
    return {
      visibleText: "",
      activeChunkIndex: null,
      phase: reveal.phase,
      passivePrefix: "",
      activeSuffix: "",
    };
  }

  const activeIdx = reveal.activeChunkIndex;
  if (activeIdx == null || reveal.phase !== "speaking") {
    return {
      visibleText: reveal.visibleText,
      activeChunkIndex: null,
      phase: reveal.phase,
      passivePrefix: reveal.visibleText,
      activeSuffix: "",
    };
  }

  const passive = joinWordChunks(reveal.displayChunks, activeIdx - 1);
  const active = reveal.displayChunks[activeIdx] ?? "";
  const visibleText = reveal.visibleText;
  const passivePrefix = passive ? `${passive} ` : "";
  const activeSuffix = active;

  return {
    visibleText,
    activeChunkIndex: activeIdx,
    phase: reveal.phase,
    passivePrefix: passive,
    activeSuffix: active,
  };
}

export function buildSpeechRevealDebugMeta(
  narrationChunks: string[],
  timestamps: number[],
  activeChunk: number | null,
  utteranceStartMs: number | null,
  completionMs: number | null,
): SpeechRevealDebugMeta {
  const firstReveal = timestamps[0] ?? null;
  return {
    narration_chunk_count: narrationChunks.length,
    chunk_reveal_timestamps: [...timestamps],
    active_speech_chunk: activeChunk,
    narration_sync_latency:
      utteranceStartMs != null && firstReveal != null ? Math.max(0, firstReveal - utteranceStartMs) : 0,
    reveal_completion_time: completionMs,
  };
}

function findProjectionForEntity(
  byLayer: Record<string, RenderProjection[]>,
  entityId: string,
): RenderProjection | null {
  for (const layer of Object.values(byLayer)) {
    for (const p of layer) {
      if (p.source_entity_id === entityId) return p;
    }
  }
  return null;
}

/** Column headers use static labels — no progressive reveal (avoids empty header row). */
export function shouldSkipSpeechRevealForProjection(projection: RenderProjection | null): boolean {
  if (!projection || projection.projection_kind !== "node") return false;
  const tier = projection.teaching_hints?.comparison_tier;
  const role = String(projection.teaching_hints?.semantic_role ?? "").toLowerCase();
  return tier === "header" || role.includes("header") || role === "column_header";
}

export function displayTextFromProjection(projection: RenderProjection): string {
  if (projection.projection_kind === "annotation") return projection.text.trim();
  if (projection.projection_kind === "label") return projection.text.trim();
  if (projection.projection_kind === "node") {
    const detail = projection.row_detail?.trim();
    if (detail) return detail;
    return projection.label.trim();
  }
  return "";
}

/** Resolve speech-reveal targets for an operation from the committed frame. */
export function extractSpeechRevealTargets(
  timeline: InstructionTimelineV3,
  operationId: string,
  byLayer: Record<string, RenderProjection[]>,
): { entityId: string; fullText: string }[] {
  const targets: { entityId: string; fullText: string }[] = [];

  for (const beat of timeline.beats) {
    const op = beat.operations.find((o) => o.operation_id === operationId);
    if (!op) continue;

    if (op.op_type === "add_entity") {
      const id = op.payload.entity.entity_id;
      const proj = findProjectionForEntity(byLayer, id);
      if (shouldSkipSpeechRevealForProjection(proj)) return targets;
      const text = proj ? displayTextFromProjection(proj) : op.payload.entity.label?.trim() ?? "";
      if (text) targets.push({ entityId: id, fullText: text });
      return targets;
    }

    if (op.op_type === "annotate_entity") {
      const annId = op.payload.annotation_id;
      const proj = findProjectionForEntity(byLayer, annId);
      const text =
        proj && proj.projection_kind === "annotation"
          ? proj.text.trim()
          : String(op.payload.text ?? "").trim();
      const targetId = op.payload.target_id;
      if (targetId) {
        const targetProj = findProjectionForEntity(byLayer, targetId);
        if (shouldSkipSpeechRevealForProjection(targetProj)) return targets;
      }
      if (/^On the (left|right):\s/i.test(text)) return targets;
      if (text) targets.push({ entityId: annId, fullText: text });
      return targets;
    }

    if (op.op_type === "connect_entities" || op.op_type === "highlight_entity") {
      const focusId = primaryEntityIdForOperation(timeline, operationId);
      if (!focusId) return targets;
      const proj = findProjectionForEntity(byLayer, focusId);
      const text = proj ? displayTextFromProjection(proj) : "";
      if (text) targets.push({ entityId: focusId, fullText: text });
      return targets;
    }
  }

  return targets;
}

function primaryEntityIdForOperation(timeline: InstructionTimelineV3, operation_id: string): string | null {
  for (const beat of timeline.beats) {
    const op = beat.operations.find((o) => o.operation_id === operation_id);
    if (!op) continue;
    if (op.op_type === "add_entity") return op.payload.entity.entity_id;
    if (op.op_type === "connect_entities") return op.payload.to_id;
    if (op.op_type === "annotate_entity") return op.payload.annotation_id;
    if (op.op_type === "highlight_entity") return op.payload.target_ids[0] ?? null;
  }
  return null;
}
