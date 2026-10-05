import type { BoardItem } from "@/components/ai/AIWhiteboard";
import type { ChatItem } from "@/hooks/useChat";

/** Instructional turns with a timeline are board-only (no duplicated prose). */
export function isBoardNativeInstructionItem(item: {
  instruction_timeline_v3?: unknown;
  timeline_metadata?: Record<string, unknown> | null;
}): boolean {
  if (item.instruction_timeline_v3 != null) return true;
  const mode = item.timeline_metadata?.instruction_display_mode;
  return mode === "board_only";
}

export function playbackStartBeatIndex(
  timelineMetadata?: Record<string, unknown> | null,
): number {
  const raw = timelineMetadata?.playback_start_beat_index;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.floor(raw);
  }
  return 0;
}

/** Partial static restore — show VTSE through this beat index only. */
export function restoreStaticThroughBeatIndex(
  timelineMetadata?: Record<string, unknown> | null,
): number | null {
  const raw = timelineMetadata?.restore_static_through_beat_index;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return Math.floor(raw);
  }
  return null;
}

export function assistantMessageHasBoardTimeline(m: ChatItem): boolean {
  return (
    m.role === "assistant" &&
    m.kind === "text" &&
    "instruction_timeline_v3" in m &&
    m.instruction_timeline_v3 != null
  );
}

export function shouldShowMicroTutorProse(
  messages: ChatItem[],
  microHold: boolean | undefined,
): boolean {
  if (microHold !== true) return false;
  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "user") {
      lastUserIdx = i;
      break;
    }
  }
  if (lastUserIdx < 0) return false;
  for (let i = lastUserIdx + 1; i < messages.length; i += 1) {
    const m = messages[i];
    if (assistantMessageHasBoardTimeline(m)) return false;
  }
  return true;
}

export function microTutorReplyText(
  messages: ChatItem[],
  microHold: boolean | undefined,
): string {
  if (!shouldShowMicroTutorProse(messages, microHold)) return "";
  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "user") {
      lastUserIdx = i;
      break;
    }
  }
  if (lastUserIdx < 0) return "";
  for (let i = lastUserIdx + 1; i < messages.length; i += 1) {
    const m = messages[i];
    if (m.role === "assistant" && m.kind === "text") {
      const c =
        typeof m.content === "string"
          ? m.content
          : m.content != null &&
              typeof m.content === "object" &&
              "text" in m.content
            ? String((m.content as { text?: string }).text ?? "")
            : "";
      return c.trim();
    }
  }
  return "";
}

export function boardItemPlaybackStart(item: BoardItem): number {
  return playbackStartBeatIndex(item.timeline_metadata ?? null);
}

export function boardItemRestoreStaticThrough(item: BoardItem): number | null {
  return restoreStaticThroughBeatIndex(item.timeline_metadata ?? null);
}
