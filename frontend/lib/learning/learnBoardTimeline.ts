/**
 * Learn whiteboard timeline — presentation ownership for board vs bubbles.
 *
 * ONE chronological timeline: durable board stages and conversational bubble
 * episodes alternate in message order. No global InlineBoardChat that gathers
 * all historical Q&A into one block (that caused Story Hook answers to appear
 * inside Zone0 and VTSE hard-exclude to dump bubbles back onto lined paper).
 */

import type { ChatItem } from "@/hooks/useChat";
import { isDurableBoardStageMessage } from "@/lib/learning/inlineBoardChat";

export type LearnBoardTimelineSegment =
  | {
      kind: "board";
      /** Durable / board-owned assistant text messages (Story Hook, VT, VTSE, intros). */
      messages: Extract<ChatItem, { role: "assistant"; kind: "text" }>[];
    }
  | {
      kind: "conversation";
      /** Chronological bubble turns for ONE episode between board stages. */
      messages: ChatItem[];
    };

function isSilentOrActionUserMessage(m: ChatItem): boolean {
  if (m.role !== "user") return false;
  if (m.conceptQuestionAction || m.clusterQuizAction) return true;
  const raw = (m.rawContent ?? m.content ?? "").trim();
  if (raw.toLowerCase().startsWith("__action:")) return true;
  return false;
}

function isAssistantText(
  m: ChatItem
): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> {
  return m.role === "assistant" && m.kind === "text";
}

function isConversationalBubbleMessage(m: ChatItem): boolean {
  if (m.role === "user") {
    if (isSilentOrActionUserMessage(m)) return false;
    if (m.conceptQuestion || m.clusterQuiz || m.clusterTeachback) return false;
    return true;
  }
  if (m.role !== "assistant") return false;
  if (m.kind === "feedback") return true;
  if (m.kind === "teachback_prompt" || m.kind === "teachback_exit") return true;
  if (m.kind === "quiz_prompt") return false;
  if (m.kind === "text") {
    if (m.clusterTeachbackTutor) return false;
    if (isDurableBoardStageMessage(m)) return false;
    return true;
  }
  return false;
}

/**
 * Walk `messages` in order and emit board vs conversation episodes.
 *
 * - Durable stage messages flush any open conversation and append to a board run.
 * - Conversational tutor/student turns flush any open board run and append to
 *   a conversation episode (closed when the next durable stage appears).
 *
 * Zone0 Q&A never shares a conversation segment with later Story Hook answers.
 */
export function buildLearnBoardTimeline(
  messages: ChatItem[]
): LearnBoardTimelineSegment[] {
  const segments: LearnBoardTimelineSegment[] = [];
  let boardBuf: Extract<ChatItem, { role: "assistant"; kind: "text" }>[] = [];
  let convoBuf: ChatItem[] = [];

  const flushBoard = () => {
    if (boardBuf.length === 0) return;
    segments.push({ kind: "board", messages: boardBuf });
    boardBuf = [];
  };
  const flushConvo = () => {
    if (convoBuf.length === 0) return;
    segments.push({ kind: "conversation", messages: convoBuf });
    convoBuf = [];
  };

  for (const m of messages) {
    if (isAssistantText(m) && isDurableBoardStageMessage(m)) {
      flushConvo();
      boardBuf.push(m);
      continue;
    }
    if (isConversationalBubbleMessage(m)) {
      flushBoard();
      convoBuf.push(m);
      continue;
    }
  }

  flushBoard();
  flushConvo();
  return segments;
}

/** Assistant text ids owned by conversation segments — must not also render on board. */
export function conversationOwnedAssistantTextIds(
  timeline: LearnBoardTimelineSegment[]
): Set<string> {
  const ids = new Set<string>();
  for (const seg of timeline) {
    if (seg.kind !== "conversation") continue;
    for (const m of seg.messages) {
      if (m.role === "assistant" && m.kind === "text") ids.add(m.id);
    }
  }
  return ids;
}

/** Flat board-owned assistant texts in timeline order (for BoardItem mapping). */
export function boardOwnedAssistantTexts(
  timeline: LearnBoardTimelineSegment[]
): Extract<ChatItem, { role: "assistant"; kind: "text" }>[] {
  const out: Extract<ChatItem, { role: "assistant"; kind: "text" }>[] = [];
  for (const seg of timeline) {
    if (seg.kind === "board") out.push(...seg.messages);
  }
  return out;
}

export function timelineHasConversation(
  timeline: LearnBoardTimelineSegment[]
): boolean {
  return timeline.some(
    (s) => s.kind === "conversation" && s.messages.length > 0
  );
}

/**
 * Latest non-action student message — owns the active conversation episode.
 * Silent `__action:` turns never create this, so they must not show thinking.
 */
export function latestVisibleStudentMessageId(
  messages: ChatItem[]
): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]!;
    if (m.role !== "user") continue;
    if (isSilentOrActionUserMessage(m)) continue;
    if (m.conceptQuestion || m.clusterQuiz || m.clusterTeachback) {
      // Panel-owned turns — not inline board conversation episodes.
      if (m.conceptQuestionAction || m.clusterQuizAction) continue;
    }
    return m.id;
  }
  return null;
}

/**
 * Thinking belongs only on the conversation episode that contains the latest
 * visible student message, and only while that student turn is still the tip
 * of the transcript (tutor reply not yet appended). Historical episodes and
 * silent `__action:` loads never show a thinking row.
 *
 * Pass `loadingKind` when available so stage-transition / ack loads cannot
 * attach conversational thinking.
 */
export function conversationEpisodeShowsThinking(
  segment: LearnBoardTimelineSegment,
  messages: ChatItem[],
  loading: boolean,
  loadingKind?: "none" | "conversation" | "stage_transition"
): boolean {
  if (!loading || segment.kind !== "conversation") return false;
  if (loadingKind != null && loadingKind !== "conversation") return false;
  const tip = messages[messages.length - 1];
  if (!tip || tip.role !== "user") return false;
  if (isSilentOrActionUserMessage(tip)) return false;
  if (tip.conceptQuestionAction || tip.clusterQuizAction) return false;
  return segment.messages.some((m) => m.id === tip.id);
}

/**
 * Durable VTSE opening timeline message id (earliest). Stage-done must fire only
 * when *this* board item completes — never when a later interrupt bubble does.
 */
export function lastVtseTimelineMessageId(
  messages: ChatItem[]
): string | null {
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]!;
    if (m.role !== "assistant" || m.kind !== "text") continue;
    if (
      "instruction_timeline_v3" in m &&
      m.instruction_timeline_v3 != null
    ) {
      return m.id;
    }
  }
  return null;
}

/**
 * True when a stream/board completion should send `__action:concept_vtse_stage_done`.
 * Interrupt Q&A bubbles must return false so VTSE can resume remaining beats.
 */
export function shouldCompleteVtseStageOnItem(
  completedItemId: string | null | undefined,
  messages: ChatItem[],
  awaitVtseDone: boolean
): boolean {
  if (!awaitVtseDone || !completedItemId) return false;
  const vtseId = lastVtseTimelineMessageId(messages);
  return vtseId != null && completedItemId === vtseId;
}

/** Identity payload so the backend can reject a stale VTSE completion. */
export function conceptVtseStageDoneAction(opts: {
  messages: ChatItem[];
  completedItemId: string;
  conceptIndex?: number;
  conceptId?: string | null;
}): string {
  const msg = opts.messages.find((m) => m.id === opts.completedItemId);
  const tl =
    msg && "instruction_timeline_v3" in msg && msg.instruction_timeline_v3
      ? (msg.instruction_timeline_v3 as {
          timeline_id?: string;
          beats?: { index?: number }[];
        })
      : null;
  const beats = Array.isArray(tl?.beats) ? tl.beats : [];
  let finalBeat = beats.length > 0 ? beats.length - 1 : 0;
  for (const beat of beats) {
    if (typeof beat?.index === "number" && beat.index > finalBeat) {
      finalBeat = beat.index;
    }
  }
  const payload = {
    concept_index: opts.conceptIndex ?? 0,
    concept_id: (opts.conceptId || "").trim(),
    timeline_id: String(tl?.timeline_id || ""),
    board_item_id: opts.completedItemId,
    final_beat_index: finalBeat,
  };
  return `__action:concept_vtse_stage_done|${JSON.stringify(payload)}`;
}
