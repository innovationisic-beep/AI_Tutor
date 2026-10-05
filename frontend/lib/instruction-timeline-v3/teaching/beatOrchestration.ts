import type {
  Beat,
  NarrationOperationBinding,
  NarrationSegment,
} from "@/lib/instruction-timeline-v3/types";
import {
  pauseAfterSegment,
  revealOffsetMs,
  type NarrationSegmentPresentationMeta,
} from "@/lib/instruction-timeline-v3/teaching/narrationSync";

export type DuringRevealStep = {
  operationId: string;
  revealOffsetMs: number;
};

/** Deterministic reveal plan for one beat (single utterance). */
export type BeatOrchestrationPlan = {
  beatId: string;
  segment: NarrationSegment;
  orchestrated: boolean;
  before: string[];
  onStart: string[];
  during: DuringRevealStep[];
  onEnd: string[];
  after: string[];
  pauseAfterMs: number;
};

function operationOrder(beat: Beat): Map<string, number> {
  const order = new Map<string, number>();
  beat.operations.forEach((op, idx) => {
    order.set(op.operation_id, idx);
  });
  return order;
}

function sortByOpOrder(ids: string[], order: Map<string, number>): string[] {
  return [...ids].sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
}

/** True when beat uses multi-op choreography on one segment. */
export function beatUsesOrchestration(beat: Beat): boolean {
  if (beat.metadata?.orchestration_v1 === true) return true;
  if (beat.bindings.length <= 1) return false;
  const segIds = new Set(beat.bindings.map((b) => b.segment_id));
  return segIds.size === 1;
}

export function primaryBeatSegment(beat: Beat): NarrationSegment | null {
  if (beat.narration_segments.length === 0) return null;
  const boundSeg = beat.bindings[0]?.segment_id;
  if (boundSeg) {
    return beat.narration_segments.find((s) => s.segment_id === boundSeg) ?? beat.narration_segments[0];
  }
  return beat.narration_segments[0];
}

export function buildBeatOrchestrationPlan(
  beat: Beat,
  fallbackPauseMs: number,
): BeatOrchestrationPlan | null {
  const segment = primaryBeatSegment(beat);
  if (!segment) return null;

  const orchestrated = beatUsesOrchestration(beat);
  const order = operationOrder(beat);
  const offsetDefault = revealOffsetMs(segment);

  const before: string[] = [];
  const onStart: string[] = [];
  const during: DuringRevealStep[] = [];
  const onEnd: string[] = [];
  const after: string[] = [];

  const push = (binding: NarrationOperationBinding) => {
    const opId = binding.operation_id;
    switch (binding.relation) {
      case "before_segment":
        before.push(opId);
        break;
      case "on_segment_start":
        onStart.push(opId);
        break;
      case "during_segment":
        during.push({ operationId: opId, revealOffsetMs: offsetDefault });
        break;
      case "on_segment_end":
        onEnd.push(opId);
        break;
      case "after_segment":
        after.push(opId);
        break;
      default:
        break;
    }
  };

  for (const binding of beat.bindings) {
    push(binding);
  }

  return {
    beatId: beat.beat_id,
    segment,
    orchestrated,
    before: sortByOpOrder(before, order),
    onStart: sortByOpOrder(onStart, order),
    during: during.sort(
      (a, b) => (order.get(a.operationId) ?? 0) - (order.get(b.operationId) ?? 0),
    ),
    onEnd: sortByOpOrder(onEnd, order),
    after: sortByOpOrder(after, order),
    pauseAfterMs: pauseAfterSegment(segment, fallbackPauseMs),
  };
}

export function segmentOrchestrationMeta(
  segment: NarrationSegment,
): NarrationSegmentPresentationMeta {
  return (segment.metadata ?? {}) as NarrationSegmentPresentationMeta;
}
