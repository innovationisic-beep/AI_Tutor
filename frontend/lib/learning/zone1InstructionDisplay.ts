import type { ChatItem } from "@/hooks/useChat";
import type { BoardItem } from "@/components/ai/AIWhiteboard";

/**
 * Emergency client opt-out for Timeline V3 visual layer under AIWhiteboard.
 * Prefer this over any backend rollout flag — product ITV3 attach is always on.
 */
export function isTimelinePresentationKillSwitchActive(): boolean {
  return process.env.NEXT_PUBLIC_TIMELINE_V3_KILL_SWITCH === "1";
}

/**
 * Dedupe key for quizHeld + explanation completion (last assistant text board item).
 */
export function getInstructionStreamingDedupeKey(messages: ChatItem[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m.role === "assistant" && m.kind === "text") return m.id;
  }
  return null;
}

function plannerSourceOf(item: BoardItem): string | null {
  if (item.planner_source) return item.planner_source;
  const dbg = item.cir_instruction_debug;
  if (dbg && typeof dbg.planner_source === "string") return dbg.planner_source;
  return null;
}

export function isLlmInstructionTimeline(item: BoardItem): boolean {
  const src = plannerSourceOf(item);
  return Boolean(src && src.includes("llm"));
}

const TEMPLATE_PLANNER_SOURCES = new Set([
  "timeline_v3_from_cir_v1",
  "timeline_v3_native",
  "timeline_v3_incremental",
]);

export function isTemplateInstructionTimeline(item: BoardItem): boolean {
  if (!item.instruction_timeline_v3) return false;
  if (isLlmInstructionTimeline(item)) return false;
  const src = plannerSourceOf(item);
  if (!src) return true;
  if (TEMPLATE_PLANNER_SOURCES.has(src)) return true;
  return src.includes("cir_v1") && !src.includes("llm");
}

function indexOfLatestInstructionTimeline(items: BoardItem[]): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].instruction_timeline_v3) return i;
  }
  return -1;
}

/**
 * Whiteboard shows one live instruction timeline (latest merged state).
 * Hides superseded template/native timelines when an LLM CIR board exists.
 */
export function filterBoardItemsForWhiteboard(items: BoardItem[]): BoardItem[] {
  const timelineIndexes = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.instruction_timeline_v3);

  if (timelineIndexes.length === 0) return items;

  let filtered = items;
  const hasLlmTimeline = timelineIndexes.some(({ item }) => isLlmInstructionTimeline(item));
  if (hasLlmTimeline) {
    filtered = filtered.filter((item) => !isTemplateInstructionTimeline(item));
  }

  const timelineCount = filtered.filter((i) => i.instruction_timeline_v3).length;
  if (timelineCount <= 1) return filtered;

  const latestIdx = indexOfLatestInstructionTimeline(filtered);
  return filtered.filter((item, index) => {
    if (!item.instruction_timeline_v3) return true;
    return index === latestIdx;
  });
}
