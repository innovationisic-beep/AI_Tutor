import type {
  Beat,
  InstructionTimelineV3,
  NarrationOperationBinding,
  NarrationSegment,
} from "@/lib/instruction-timeline-v3/types";

/**
 * Optional keys planners may place on NarrationSegment.metadata (validated as unknown).
 * Use for deterministic pacing without AI-derived timings.
 */
export type NarrationSegmentPresentationMeta = {
  /** Pause after this segment's speech ends, before the next visual step (ms). */
  pause_after_ms?: number;
  /** For `during_segment`: reveal this many ms after utterance starts. */
  reveal_offset_ms?: number;
  /** Hint: prefer revealing annotations after spoken introduction (layout-only consumers). */
  reveal_after_speech?: boolean;
  /** Hint: reveal during the spoken phrase (pairs with reveal_offset_ms). */
  reveal_during_speech?: boolean;
};

export function findNarrationBinding(
  timeline: InstructionTimelineV3,
  operation_id: string,
): { beat: Beat; segment: NarrationSegment; binding: NarrationOperationBinding } | null {
  for (const beat of timeline.beats) {
    const binding = beat.bindings.find((b) => b.operation_id === operation_id);
    if (!binding) continue;
    const segment = beat.narration_segments.find((s) => s.segment_id === binding.segment_id);
    if (segment) return { beat, segment, binding };
  }
  return null;
}

/** Primary entity id this operation introduces or emphasizes (for teaching focus). */
export function primaryEntityIdForOperation(
  timeline: InstructionTimelineV3,
  operation_id: string,
): string | null {
  for (const beat of timeline.beats) {
    const op = beat.operations.find((o) => o.operation_id === operation_id);
    if (!op) continue;
    if (op.op_type === "add_entity") return op.payload.entity.entity_id;
    if (op.op_type === "connect_entities") return op.payload.to_id;
    if (op.op_type === "annotate_entity") return op.payload.target_id;
    if (op.op_type === "highlight_entity") return op.payload.target_ids[0] ?? null;
  }
  return null;
}

export function pauseAfterSegment(segment: NarrationSegment, fallbackMs: number): number {
  const m = segment.metadata as NarrationSegmentPresentationMeta | undefined;
  if (typeof m?.pause_after_ms === "number" && m.pause_after_ms >= 0) return m.pause_after_ms;
  if (segment.timing.fallback_delay_ms != null) return segment.timing.fallback_delay_ms;
  return Math.max(120, segment.timing.min_visible_ms ?? fallbackMs);
}

export function revealOffsetMs(segment: NarrationSegment): number {
  const m = segment.metadata as NarrationSegmentPresentationMeta | undefined;
  if (typeof m?.reveal_offset_ms === "number") return Math.max(0, m.reveal_offset_ms);
  return 0;
}

export function timelineHasNarrationSync(timeline: InstructionTimelineV3): boolean {
  return timeline.beats.some((b) => b.narration_segments.length > 0 && b.bindings.length > 0);
}
