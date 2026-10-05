/**
 * Zone 0 tutor prose lives on the whiteboard — not duplicated in the chat column.
 */

import type { ChatItem } from "@/hooks/useChat";

/** Hide board-only Zone 0 assistant bubbles from the chat sidebar. */
export function filterZone0ProseFromChat(messages: ChatItem[]): ChatItem[] {
  return messages.filter((m) => {
    if (m.role === "user") return true;
    if (m.role !== "assistant") return true;
    if (m.kind === "text" || m.kind === "quiz_prompt") return false;
    return true;
  });
}

export function isZone0LearningUi(
  currentZone: number | undefined,
  flowState: string | undefined
): boolean {
  if ((currentZone ?? -1) === 0) return true;
  return (
    flowState === "zone0_anchor" ||
    flowState === "zone0_prereq" ||
    flowState === "zone0_curiosity" ||
    flowState === "zone0_mirror" ||
    flowState === "pedagogy_session_intro" ||
    flowState === "pedagogy_cluster_intro" ||
    flowState === "pedagogy_session_recall" ||
    flowState === "pedagogy_session_recall_feedback" ||
    flowState === "pedagogy_cluster_curiosity" ||
    flowState === "pedagogy_cluster_curiosity_feedback"
  );
}
