import type { InstructionTimelineV3 } from "./types";

type TimelineCarrier = {
  instruction_timeline_v3?: InstructionTimelineV3 | null;
};

function cloneTimeline(t: InstructionTimelineV3): InstructionTimelineV3 {
  return JSON.parse(JSON.stringify(t)) as InstructionTimelineV3;
}

/** Merge Zone 1 assistant timelines that share the same `timeline_id` (chronological). */
export function mergeZone1TimelinesFromMessages(
  messages: TimelineCarrier[],
): InstructionTimelineV3 | null {
  if (!messages.length) return null;
  let merged: InstructionTimelineV3 | null = null;
  const seenBeatIds = new Set<string>();

  for (const m of messages) {
    const raw = m.instruction_timeline_v3;
    if (!raw || typeof raw !== "object") continue;
    const t = raw as InstructionTimelineV3;
    const tid = t.timeline_id;
    if (!tid) continue;

    if (!merged || merged.timeline_id !== tid) {
      merged = cloneTimeline(t);
      seenBeatIds.clear();
      for (const b of merged.beats ?? []) {
        if (b?.beat_id) seenBeatIds.add(String(b.beat_id));
      }
      continue;
    }

    for (const b of t.beats ?? []) {
      const id = b?.beat_id != null ? String(b.beat_id) : "";
      if (!id || seenBeatIds.has(id)) continue;
      seenBeatIds.add(id);
      merged.beats = [...(merged.beats ?? []), b];
    }
  }

  return merged;
}
