import type { ChatHistoryMessage, TutorVisual } from "./types";
import type { ChatItem } from "@/hooks/useChat";
import { mapHistoryRowToChatItem } from "./chatHistory";

const ZONE0_PROSE_TYPES = new Set([
  "zone0_anchor",
  "zone0_curiosity",
  "zone0_mirror",
  "zone0_prereq",
  "session_intro_card",
  "cluster_intro_card",
  "session_recall_prompt",
  "session_recall_feedback",
  "cluster_curiosity_prompt",
  "cluster_curiosity_feedback",
]);

export type SessionBoardTurnSnapshot = {
  turn_index: number;
  content: string;
  instruction_timeline_v3?: Record<string, unknown> | null;
  timeline_metadata?: Record<string, unknown> | null;
  planner_source?: string | null;
  visual?: TutorVisual | null;
  zone?: number | null;
  cluster_index?: number | null;
  concept_index?: number | null;
  concept_id?: string | null;
  response_type?: string | null;
  created_at: string;
};

export type SessionRestorePayload = {
  session_id: string;
  topic_id: string;
  flow_state: string;
  current_concept?: string | null;
  current_concept_index?: number | null;
  total_concepts?: number | null;
  current_zone?: number | null;
  meta?: Record<string, unknown> | null;
  messages: ChatHistoryMessage[];
  board_turns: SessionBoardTurnSnapshot[];
  restore_static_beat_index?: number | null;
  restore_suppress_concept_questions?: boolean;
  student_scratchpad_notes?: string | null;
  progression?: import("./types").PlanProgressionView | null;
};

function uid(prefix: string, turn: SessionBoardTurnSnapshot) {
  return `${prefix}-bt-${turn.turn_index}`;
}

/** Rebuild Zone 0 prose segments missing from persisted board turns (legacy sessions). */
export function supplementBoardTurnsFromHistoryMessages(
  messages: ChatHistoryMessage[],
  boardTurns: SessionBoardTurnSnapshot[]
): SessionBoardTurnSnapshot[] {
  const existingKeys = new Set<string>();
  for (const turn of boardTurns) {
    const key = (turn.content || "").trim().toLowerCase();
    if (key) existingKeys.add(key);
    const rt = (turn.response_type || "").trim();
    if (rt && ZONE0_PROSE_TYPES.has(rt) && key) {
      existingKeys.add(`type:${rt}:${key.slice(0, 120)}`);
    }
  }

  const supplements: SessionBoardTurnSnapshot[] = [];
  let supplementIndex = -1000;
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    const mt = (msg.message_type || "").trim();
    const content = (msg.content || "").trim();
    if (!content || !ZONE0_PROSE_TYPES.has(mt)) continue;
    const dedupeKey = `type:${mt}:${content.toLowerCase().slice(0, 120)}`;
    if (existingKeys.has(content.toLowerCase()) || existingKeys.has(dedupeKey)) {
      continue;
    }
    supplements.push({
      turn_index: supplementIndex,
      content,
      instruction_timeline_v3: null,
      timeline_metadata: null,
      planner_source: null,
      visual: null,
      zone: 0,
      cluster_index: 0,
      concept_index: 0,
      concept_id: null,
      response_type: mt,
      created_at: msg.created_at,
    });
    supplementIndex -= 1;
    existingKeys.add(content.toLowerCase());
    existingKeys.add(dedupeKey);
  }

  if (supplements.length === 0) return boardTurns;

  const merged = [...supplements, ...boardTurns];
  merged.sort((a, b) => {
    const ta = a.created_at || "";
    const tb = b.created_at || "";
    if (ta < tb) return -1;
    if (ta > tb) return 1;
    return (a.turn_index || 0) - (b.turn_index || 0);
  });
  return merged.map((row, i) => ({ ...row, turn_index: i }));
}

export function boardTurnToChatItem(
  turn: SessionBoardTurnSnapshot,
  prefix = "restore"
): ChatItem {
  const itv3 = turn.instruction_timeline_v3 ?? null;
  const visual = turn.visual ?? null;
  let writingMode: "legacy" | "notes" | undefined;
  let displayText: string | undefined;
  let boardWrites: Array<{ sentenceIndex: number; text: string }> | undefined;
  if (visual && typeof visual === "object") {
    const wm = visual.writing_mode;
    if (wm === "notes" || wm === "legacy") {
      writingMode = wm;
    }
    if (writingMode === "notes" && typeof visual.display_text === "string") {
      displayText = visual.display_text;
    } else if (writingMode === "notes") {
      displayText = "";
    }
    if (writingMode === "notes" && Array.isArray(visual.writes)) {
      const parsed: Array<{ sentenceIndex: number; text: string }> = [];
      for (const item of visual.writes) {
        if (!item || typeof item !== "object") continue;
        const rec = item as Record<string, unknown>;
        const idx = Number(rec.sentence_index);
        const text = typeof rec.text === "string" ? rec.text.trim() : "";
        if (!Number.isFinite(idx) || idx < 0 || !text) continue;
        parsed.push({ sentenceIndex: Math.floor(idx), text });
      }
      if (parsed.length) boardWrites = parsed;
    }
  }
  return {
    id: uid(prefix, turn),
    role: "assistant",
    kind: "text",
    content: turn.content || "",
    visual,
    ...(itv3 != null ? { instruction_timeline_v3: itv3 } : {}),
    ...(turn.planner_source != null ? { planner_source: turn.planner_source } : {}),
    ...(turn.timeline_metadata != null
      ? { timeline_metadata: turn.timeline_metadata }
      : {}),
    ...(writingMode != null ? { writingMode } : {}),
    ...(displayText !== undefined ? { displayText } : {}),
    ...(boardWrites ? { boardWrites } : {}),
  };
}

/** Merge persisted board turns with chat history for a unified message list. */
export function buildRestoredChatItems(
  messages: ChatHistoryMessage[],
  boardTurns: SessionBoardTurnSnapshot[],
  pendingBoard?: SessionBoardTurnSnapshot | null
): ChatItem[] {
  const chatItems = messages
    .map((r, i) => mapHistoryRowToChatItem(r, i))
    .filter((item): item is NonNullable<typeof item> => item != null) as ChatItem[];

  if (boardTurns.length === 0 && !pendingBoard) {
    return chatItems;
  }

  const turns = [...boardTurns];
  if (pendingBoard?.instruction_timeline_v3) {
    const last = turns[turns.length - 1];
    const pendingId = pendingBoard.instruction_timeline_v3?.timeline_id;
    const lastId =
      last?.instruction_timeline_v3 &&
      typeof last.instruction_timeline_v3 === "object"
        ? (last.instruction_timeline_v3 as { timeline_id?: string }).timeline_id
        : null;
    if (pendingId && pendingId === lastId) {
      turns[turns.length - 1] = {
        ...last,
        instruction_timeline_v3: pendingBoard.instruction_timeline_v3,
        timeline_metadata: pendingBoard.timeline_metadata ?? last.timeline_metadata,
      };
    } else {
      turns.push(pendingBoard);
    }
  }

  const textAssistantIdx: number[] = [];
  chatItems.forEach((m, i) => {
    if (m.role === "assistant" && m.kind === "text") textAssistantIdx.push(i);
  });

  let cursor = 0;
  for (const turn of turns) {
    if (!turn.instruction_timeline_v3) continue;
    let attached = false;
    for (let j = cursor; j < textAssistantIdx.length; j += 1) {
      const idx = textAssistantIdx[j];
      const item = chatItems[idx];
      if (item.role !== "assistant" || item.kind !== "text") continue;
      const hasTimeline =
        "instruction_timeline_v3" in item && item.instruction_timeline_v3 != null;
      if (hasTimeline) continue;
      const turnContent = (turn.content || "").trim();
      const itemContent = (item.content || "").trim();
      if (!turnContent || !itemContent || turnContent === itemContent) {
        chatItems[idx] = {
          ...item,
          ...(turn.instruction_timeline_v3 != null
            ? { instruction_timeline_v3: turn.instruction_timeline_v3 }
            : {}),
          ...(turn.planner_source != null
            ? { planner_source: turn.planner_source }
            : {}),
          ...(turn.timeline_metadata != null
            ? { timeline_metadata: turn.timeline_metadata }
            : {}),
          ...(turn.visual != null ? { visual: turn.visual } : {}),
        };
        cursor = j + 1;
        attached = true;
        break;
      }
    }
    if (!attached) {
      chatItems.push(boardTurnToChatItem(turn));
    }
  }

  return chatItems;
}

export function persistedBoardTurnsFromRestore(
  boardTurns: SessionBoardTurnSnapshot[],
  pendingBoard?: SessionBoardTurnSnapshot | null
): SessionBoardTurnSnapshot[] {
  const turns = [...boardTurns];
  if (!pendingBoard?.instruction_timeline_v3) return turns;
  const pendingId = (
    pendingBoard.instruction_timeline_v3 as { timeline_id?: string }
  ).timeline_id;
  const last = turns[turns.length - 1];
  const lastId =
    last?.instruction_timeline_v3 &&
    typeof last.instruction_timeline_v3 === "object"
      ? (last.instruction_timeline_v3 as { timeline_id?: string }).timeline_id
      : null;
  if (pendingId && pendingId === lastId && last) {
    turns[turns.length - 1] = {
      ...last,
      instruction_timeline_v3: pendingBoard.instruction_timeline_v3,
      timeline_metadata: {
        ...(last.timeline_metadata ?? {}),
        ...(pendingBoard.timeline_metadata ?? {}),
      },
    };
    return turns;
  }
  return [...turns, pendingBoard];
}

/** Build static-restore map: item id → beat index (-1 = prose-only static). */
export function staticRestoreMapFromTurns(
  turns: SessionBoardTurnSnapshot[]
): Record<string, number> {
  const map: Record<string, number> = {};
  let lastTimelineIdx = -1;
  turns.forEach((t, i) => {
    if (t.instruction_timeline_v3) lastTimelineIdx = i;
  });
  turns.forEach((t, i) => {
    const id = boardTurnToChatItem(t).id;
    const through = t.timeline_metadata?.restore_static_through_beat_index;
    if (typeof through === "number" && Number.isFinite(through) && through >= 0) {
      map[id] = Math.floor(through);
      return;
    }
    if (t.instruction_timeline_v3) {
      const beats = (t.instruction_timeline_v3 as { beats?: unknown[] }).beats;
      if (i < lastTimelineIdx && Array.isArray(beats) && beats.length > 0) {
        map[id] = beats.length - 1;
      } else if (i === lastTimelineIdx && Array.isArray(beats) && beats.length > 0) {
        map[id] = 0;
      }
      return;
    }
    if ((t.content || "").trim()) {
      map[id] = -1;
    }
  });
  return map;
}

/** Fallback static-restore map from chat when board turns were not persisted. */
export function staticRestoreMapFromChatItems(
  textMessages: Extract<ChatItem, { role: "assistant"; kind: "text" }>[],
  restoreStaticBeatIndex: number | null | undefined
): Record<string, number> {
  const map: Record<string, number> = {};
  let lastTimelineItemId: string | null = null;
  let lastTimelineBeats = 0;

  for (const m of textMessages) {
    const itv3 =
      "instruction_timeline_v3" in m && m.instruction_timeline_v3 != null
        ? (m.instruction_timeline_v3 as { beats?: unknown[] })
        : null;
    if (itv3) {
      lastTimelineItemId = m.id;
      lastTimelineBeats = Array.isArray(itv3.beats) ? itv3.beats.length : 0;
      continue;
    }
    const content =
      typeof m.content === "string"
        ? m.content.trim()
        : m.content != null &&
            typeof m.content === "object" &&
            "text" in m.content
          ? String((m.content as { text?: string }).text ?? "").trim()
          : "";
    if (content) map[m.id] = -1;
  }

  if (!lastTimelineItemId) return map;

  const lastItem = textMessages.find((m) => m.id === lastTimelineItemId);
  const tmeta =
    lastItem && "timeline_metadata" in lastItem
      ? (lastItem.timeline_metadata as Record<string, unknown> | null)
      : null;
  const through = tmeta?.restore_static_through_beat_index;
  if (typeof through === "number" && Number.isFinite(through) && through >= 0) {
    map[lastTimelineItemId] = Math.floor(through);
  } else if (typeof restoreStaticBeatIndex === "number") {
    map[lastTimelineItemId] = restoreStaticBeatIndex;
  } else if (restoreStaticBeatIndex === null && lastTimelineBeats > 0) {
    map[lastTimelineItemId] = lastTimelineBeats - 1;
  } else if (lastTimelineBeats > 0) {
    map[lastTimelineItemId] = 0;
  }

  return map;
}
