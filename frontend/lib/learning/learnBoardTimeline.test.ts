/**
 * Stage-anchored learn board timeline.
 * Run: npx tsx --test lib/learning/learnBoardTimeline.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ChatItem } from "@/hooks/useChat";
import {
  buildLearnBoardTimeline,
  conversationEpisodeShowsThinking,
  conversationOwnedAssistantTextIds,
  lastVtseTimelineMessageId,
  shouldCompleteVtseStageOnItem,
} from "./learnBoardTimeline";

describe("buildLearnBoardTimeline", () => {
  it("keeps Zone0 conversation closed before Story Hook; Hook answer is separate episode", () => {
    const msgs: ChatItem[] = [
      {
        id: "intro",
        role: "assistant",
        kind: "text",
        content: "Session overview",
        visual: { type: "pedagogy_intro", card: {} },
      },
      { id: "q1", role: "assistant", kind: "text", content: "Zone0 Q1?" },
      { id: "a1", role: "user", kind: "text", content: "ans1" },
      { id: "q2", role: "assistant", kind: "text", content: "Zone0 Q2?" },
      { id: "a2", role: "user", kind: "text", content: "ans2" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "Story hook body",
        visual: { type: "concept_story_hook", card: {} },
      },
      { id: "sha", role: "user", kind: "text", content: "hook answer" },
      {
        id: "shf",
        role: "assistant",
        kind: "text",
        content: "Nice — let's continue.",
      },
    ];

    const tl = buildLearnBoardTimeline(msgs);
    assert.deepEqual(
      tl.map((s) => s.kind),
      ["board", "conversation", "board", "conversation"]
    );
    assert.deepEqual(
      tl[0]!.kind === "board" ? tl[0].messages.map((m) => m.id) : [],
      ["intro"]
    );
    assert.deepEqual(
      tl[1]!.kind === "conversation" ? tl[1].messages.map((m) => m.id) : [],
      ["q1", "a1", "q2", "a2"]
    );
    assert.deepEqual(
      tl[2]!.kind === "board" ? tl[2].messages.map((m) => m.id) : [],
      ["sh"]
    );
    assert.deepEqual(
      tl[3]!.kind === "conversation" ? tl[3].messages.map((m) => m.id) : [],
      ["sha", "shf"]
    );

    // Hook answer must NOT appear in the Zone0 conversation block.
    const zone0 =
      tl[1]!.kind === "conversation" ? tl[1].messages.map((m) => m.id) : [];
    assert.equal(zone0.includes("sha"), false);
  });

  it("VTSE durable timeline stays board-owned; prior bubbles remain as prior episodes", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q?" },
      { id: "a1", role: "user", kind: "text", content: "A" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "hook",
        visual: { type: "concept_story_hook", card: {} },
      },
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "timeline",
        instruction_timeline_v3: { beats: [] },
      },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    // Consecutive durable stages share one board run (Story Hook + VTSE).
    assert.deepEqual(
      tl.map((s) => s.kind),
      ["conversation", "board"]
    );
    assert.deepEqual(
      tl[1]!.kind === "board" ? tl[1].messages.map((m) => m.id) : [],
      ["sh", "vtse"]
    );
    assert.ok(tl.some((s) => s.kind === "conversation"));
    const omit = conversationOwnedAssistantTextIds(tl);
    assert.ok(omit.has("q1"));
    assert.equal(omit.has("vtse"), false);
    assert.equal(omit.has("sh"), false);
  });

  it("one presentation: conversation-owned ids are exactly non-durable bubble texts", () => {
    const msgs: ChatItem[] = [
      { id: "t1", role: "assistant", kind: "text", content: "hi" },
      { id: "u1", role: "user", kind: "text", content: "yo" },
      {
        id: "vt",
        role: "assistant",
        kind: "text",
        content: "visual",
        visual: { type: "concept_visual_teaching", card: {} },
      },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    const omit = conversationOwnedAssistantTextIds(tl);
    assert.deepEqual([...omit].sort(), ["t1"]);
  });
});

describe("thinking placement (active episode only)", () => {
  it("shows thinking only on the episode with the latest student message", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Zone0?" },
      { id: "a1", role: "user", kind: "text", content: "ans" },
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "board",
        instruction_timeline_v3: { beats: [{ id: "b1" }] },
      },
      { id: "sq", role: "user", kind: "text", content: "What is X?" },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    assert.deepEqual(
      tl.map((s) => s.kind),
      ["conversation", "board", "conversation"]
    );
    const zone0 = tl[0]!;
    const interrupt = tl[2]!;
    assert.equal(conversationEpisodeShowsThinking(zone0, msgs, true), false);
    assert.equal(conversationEpisodeShowsThinking(interrupt, msgs, true), true);
    assert.equal(conversationEpisodeShowsThinking(interrupt, msgs, false), false);
    assert.equal(
      conversationEpisodeShowsThinking(interrupt, msgs, true, "conversation"),
      true
    );
    assert.equal(
      conversationEpisodeShowsThinking(
        interrupt,
        msgs,
        true,
        "stage_transition"
      ),
      false
    );
  });

  it("silent actions do not attach thinking to a historical episode", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q?" },
      { id: "a1", role: "user", kind: "text", content: "A" },
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "board",
        instruction_timeline_v3: { beats: [] },
      },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    const zone0 = tl[0]!;
    // loading from silent __action: — no new student message → no thinking row
    assert.equal(conversationEpisodeShowsThinking(zone0, msgs, true), false);
  });
});

describe("VTSE interrupt must not complete stage early", () => {
  it("interrupt bubble completion does not stage-done; VTSE board id does", () => {
    const msgs: ChatItem[] = [
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "step1 step2",
        instruction_timeline_v3: { beats: [{ id: "1" }, { id: "2" }] },
      },
      { id: "sq", role: "user", kind: "text", content: "Why?" },
      {
        id: "ans",
        role: "assistant",
        kind: "text",
        content: "Because… let's continue.",
      },
    ];
    assert.equal(lastVtseTimelineMessageId(msgs), "vtse");
    assert.equal(
      shouldCompleteVtseStageOnItem("ans", msgs, true),
      false,
      "tutor interrupt answer must not complete VTSE"
    );
    assert.equal(
      shouldCompleteVtseStageOnItem("vtse", msgs, true),
      true,
      "VTSE board timeline completion resumes stage-done"
    );
    assert.equal(
      shouldCompleteVtseStageOnItem("vtse", msgs, false),
      false,
      "without await flag, never stage-done"
    );
  });

  it("chronological order: VTSE board then interrupt episode", () => {
    const msgs: ChatItem[] = [
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "timeline",
        instruction_timeline_v3: { beats: [] },
      },
      { id: "sq", role: "user", kind: "text", content: "Question?" },
      { id: "ans", role: "assistant", kind: "text", content: "Answer." },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    assert.deepEqual(
      tl.map((s) => s.kind),
      ["board", "conversation"]
    );
    assert.deepEqual(
      tl[1]!.kind === "conversation" ? tl[1].messages.map((m) => m.id) : [],
      ["sq", "ans"]
    );
  });
});
