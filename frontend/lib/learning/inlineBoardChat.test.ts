/**
 * Inline board chat predicates + chronological thread filters.
 * Run: npx tsx --test lib/learning/inlineBoardChat.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ChatItem } from "@/hooks/useChat";
import type { SessionUiState } from "@/lib/tutorFlow";
import { INITIAL_UI } from "@/lib/tutorFlow";
import {
  filterInlineBoardChatMessages,
  inlineConversationBoardOmitIds,
  isInlineChatExcludedStage,
  isInlineChatHardExcludedStage,
  isConversationalEpisodeMode,
  resolveInlineBoardChatHistoryMode,
  resolveInlineBoardChatMode,
  splitBoardItemsAroundInlineThread,
  resolveLatestStreamableAssistantId,
  shouldShowBoardActionButtons,
  shouldShowBoardComposer,
  shouldShowBoardQuizBox,
  shouldShowBoardTeachbackInput,
  shouldShowInlineBoardChat,
  shouldShowInlineBoardChatHistory,
  isFullWidthBoardLayout,
  isDurableBoardStageMessage,
} from "./inlineBoardChat";

function ui(partial: Partial<SessionUiState>): SessionUiState {
  return {
    ...INITIAL_UI,
    currentZone: 1,
    ...partial,
    sessionMeta: partial.sessionMeta
      ? { ...(INITIAL_UI.sessionMeta ?? {}), ...partial.sessionMeta }
      : INITIAL_UI.sessionMeta,
  };
}

describe("full-width board layout", () => {
  it("always uses full-width board (no permanent right column)", () => {
    assert.equal(isFullWidthBoardLayout(), true);
  });
});

describe("inline-chat flow predicate", () => {
  it("VTSE / visual teaching → hard-exclude (no inline history)", () => {
    assert.equal(
      shouldShowInlineBoardChat(ui({ flowState: "concept_visual_teaching" })),
      false
    );
    assert.equal(
      shouldShowInlineBoardChat(ui({ flowState: "concept_vtse_opening" })),
      false
    );
    assert.equal(
      isInlineChatHardExcludedStage(ui({ flowState: "concept_visual_teaching" })),
      true
    );
    assert.equal(
      isInlineChatHardExcludedStage(ui({ flowState: "concept_vtse_opening" })),
      true
    );
  });

  it("story hook narration alone (no prior episode) → no empty bubble strip", () => {
    assert.equal(
      shouldShowInlineBoardChatHistory(ui({ flowState: "concept_story_hook" })),
      false
    );
    assert.equal(
      isInlineChatHardExcludedStage(ui({ flowState: "concept_story_hook" })),
      false
    );
  });

  it("zone0 awaiting response → inline chat", () => {
    for (const flow of [
      "zone0_anchor",
      "zone0_prereq",
      "zone0_curiosity",
    ] as const) {
      assert.equal(
        shouldShowInlineBoardChat(ui({ flowState: flow, currentZone: 0 })),
        true
      );
      assert.equal(
        resolveInlineBoardChatMode(ui({ flowState: flow, currentZone: 0 })),
        "zone0_answer"
      );
    }
  });

  it("story hook awaiting → inline chat", () => {
    const state = ui({
      flowState: "concept_story_hook",
      sessionMeta: {
        zone: 1,
        cluster_index: 0,
        total_clusters: 1,
        concept_index: 0,
        total_concepts: 1,
        story_hook_awaiting: true,
      },
    });
    assert.equal(shouldShowInlineBoardChat(state), true);
    assert.equal(resolveInlineBoardChatMode(state), "story_hook_await");
  });

  it("pedagogy recall / curiosity → inline chat", () => {
    assert.equal(
      resolveInlineBoardChatMode(ui({ flowState: "pedagogy_session_recall" })),
      "pedagogy_recall"
    );
    assert.equal(
      resolveInlineBoardChatMode(ui({ flowState: "pedagogy_cluster_curiosity" })),
      "pedagogy_curiosity"
    );
  });

  it("clarity teachback mode → inline chat", () => {
    assert.equal(
      resolveInlineBoardChatMode(ui({ flowState: "explaining" }), {
        isTeachbackMode: true,
      }),
      "clarity_teachback"
    );
    assert.equal(
      shouldShowBoardTeachbackInput({ isTeachbackMode: true }),
      true
    );
  });

  it("waiting_for_question → inline chat + composer", () => {
    const state = ui({ flowState: "waiting_for_question" });
    assert.equal(shouldShowInlineBoardChat(state), true);
    assert.equal(shouldShowBoardComposer(state), true);
  });

  it("composer hidden when text input is not expected", () => {
    assert.equal(
      shouldShowBoardComposer(ui({ flowState: "concept_visual_teaching" })),
      false
    );
    assert.equal(
      shouldShowBoardComposer(ui({ flowState: "zone0_mirror", currentZone: 0 })),
      false
    );
    assert.equal(
      shouldShowBoardComposer(ui({ flowState: "concept_questions" }), {
        conceptQuestionsActive: true,
      }),
      false
    );
  });

  it("concept check / cluster quiz keep board panels (no side composer)", () => {
    assert.equal(
      shouldShowBoardComposer(
        ui({
          flowState: "concept_questions",
          sessionMeta: {
            zone: 1,
            cluster_index: 0,
            total_clusters: 1,
            concept_index: 0,
            total_concepts: 1,
            concept_questions_active: true,
            micro_quiz_hold: 1,
            concept_question_type: "fill_in_blank",
          },
        }),
        { conceptQuestionsActive: true }
      ),
      false
    );
  });
});

describe("history vs input vs loading (separate predicates)", () => {
  it("history stays visible when input is temporarily disabled (zone0_mirror)", () => {
    const state = ui({ flowState: "zone0_mirror", currentZone: 0 });
    assert.equal(shouldShowInlineBoardChatHistory(state), true);
    assert.equal(resolveInlineBoardChatHistoryMode(state), "zone0_answer");
    assert.equal(shouldShowBoardComposer(state), false);
  });

  it("history stays visible during pedagogy feedback (composer off)", () => {
    const recallFb = ui({ flowState: "pedagogy_session_recall_feedback" });
    assert.equal(shouldShowInlineBoardChatHistory(recallFb), true);
    assert.equal(resolveInlineBoardChatHistoryMode(recallFb), "pedagogy_recall");
    assert.equal(shouldShowBoardComposer(recallFb), false);

    const curFb = ui({ flowState: "pedagogy_cluster_curiosity_feedback" });
    assert.equal(shouldShowInlineBoardChatHistory(curFb), true);
    assert.equal(
      resolveInlineBoardChatHistoryMode(curFb),
      "pedagogy_curiosity"
    );
  });

  it("existing history mode held when loading=true and flow flips transiently", () => {
    const midRequest = ui({ flowState: "explaining", currentZone: 1 });
    assert.equal(
      resolveInlineBoardChatHistoryMode(midRequest, {
        loading: true,
        stickyMode: "pedagogy_recall",
      }),
      "pedagogy_recall"
    );
    assert.equal(
      shouldShowInlineBoardChatHistory(midRequest, {
        loading: true,
        stickyMode: "pedagogy_recall",
      }),
      true
    );
  });

  it("zone0 episode holds history through explaining/idle without sticky", () => {
    assert.equal(
      resolveInlineBoardChatHistoryMode(
        ui({ flowState: "explaining", currentZone: 0 })
      ),
      "zone0_answer"
    );
    assert.equal(
      resolveInlineBoardChatHistoryMode(
        ui({ flowState: "idle", currentZone: 0 })
      ),
      "zone0_answer"
    );
  });

  it("sending does not clear filter — same mode keeps chronological thread", () => {
    const thread: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q1?" },
      { id: "a1", role: "user", kind: "text", content: "A1" },
    ];
    const before = filterInlineBoardChatMessages(thread, "zone0_answer");
    const mode = resolveInlineBoardChatHistoryMode(
      ui({ flowState: "explaining", currentZone: 0 }),
      { loading: true, stickyMode: "zone0_answer" }
    );
    const during = filterInlineBoardChatMessages(thread, mode);
    assert.deepEqual(
      during.map((m) => m.id),
      before.map((m) => m.id)
    );
  });

  it("hard-excluded stages stay off even with sticky + loading", () => {
    assert.equal(
      shouldShowInlineBoardChatHistory(
        ui({ flowState: "concept_visual_teaching" }),
        { loading: true, stickyMode: "zone0_answer" }
      ),
      false
    );
    assert.equal(
      shouldShowInlineBoardChatHistory(
        ui({ flowState: "concept_vtse_opening" }),
        { loading: true, stickyMode: "pedagogy_recall" }
      ),
      false
    );
  });

  it("Story Hook narration keeps Zone0 episode history + bubble omit", () => {
    const storyHookNarration = ui({
      flowState: "concept_story_hook",
      currentZone: 1,
      sessionMeta: {
        zone: 1,
        cluster_index: 0,
        total_clusters: 1,
        concept_index: 0,
        total_concepts: 1,
        story_hook_awaiting: false,
      },
    });
    assert.equal(isInlineChatHardExcludedStage(storyHookNarration), false);
    assert.equal(
      resolveInlineBoardChatHistoryMode(storyHookNarration, {
        stickyMode: "zone0_answer",
      }),
      "zone0_answer"
    );
    assert.equal(
      shouldShowInlineBoardChatHistory(storyHookNarration, {
        stickyMode: "zone0_answer",
      }),
      true
    );
    // Composer stays off during narration.
    assert.equal(shouldShowBoardComposer(storyHookNarration), false);

    const thread: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Zone0 Q?" },
      { id: "a1", role: "user", kind: "text", content: "my reply" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "Story hook body",
        visual: { type: "concept_story_hook", card: {} },
      },
    ];
    const mode = resolveInlineBoardChatHistoryMode(storyHookNarration, {
      stickyMode: "zone0_answer",
    });
    const filtered = filterInlineBoardChatMessages(thread, mode);
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["q1", "a1"]
    );
    const omit = inlineConversationBoardOmitIds(thread, mode);
    assert.ok(omit.has("q1"));
    assert.equal(omit.has("sh"), false);
    assert.equal(isDurableBoardStageMessage(thread[2]!), true);
  });

  it("Story Hook awaiting prefers Zone0 sticky over answers-only mode", () => {
    const awaiting = ui({
      flowState: "concept_story_hook",
      currentZone: 1,
      sessionMeta: {
        zone: 1,
        cluster_index: 0,
        total_clusters: 1,
        concept_index: 0,
        total_concepts: 1,
        story_hook_awaiting: true,
      },
    });
    assert.equal(
      resolveInlineBoardChatHistoryMode(awaiting, {
        stickyMode: "zone0_answer",
      }),
      "zone0_answer"
    );
    assert.equal(isConversationalEpisodeMode("zone0_answer"), true);
    assert.equal(isConversationalEpisodeMode("story_hook_await"), false);
  });

  it("flow order: intros above chat, Story Hook below", () => {
    const msgs: ChatItem[] = [
      {
        id: "intro",
        role: "assistant",
        kind: "text",
        content: "Session intro",
        visual: { type: "pedagogy_intro", card: {} },
      },
      {
        id: "cluster",
        role: "assistant",
        kind: "text",
        content: "Cluster intro",
        visual: { type: "pedagogy_intro", card: {} },
      },
      { id: "q1", role: "assistant", kind: "text", content: "Q1?" },
      { id: "a1", role: "user", kind: "text", content: "A1" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "hook",
        visual: { type: "concept_story_hook", card: {} },
      },
    ];
    const thread = filterInlineBoardChatMessages(msgs, "zone0_answer");
    const board = [
      { id: "intro" },
      { id: "cluster" },
      { id: "sh" },
    ];
    const split = splitBoardItemsAroundInlineThread(msgs, thread, board);
    assert.deepEqual(
      split.before.map((b) => b.id),
      ["intro", "cluster"]
    );
    assert.deepEqual(
      split.after.map((b) => b.id),
      ["sh"]
    );
    assert.deepEqual(
      thread.map((m) => m.id),
      ["q1", "a1"]
    );
  });

  it("Zone0 then Story Hook only → chat then hook", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q1?" },
      { id: "a1", role: "user", kind: "text", content: "A1" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "hook",
        visual: { type: "concept_story_hook", card: {} },
      },
    ];
    const thread = filterInlineBoardChatMessages(msgs, "zone0_answer");
    const split = splitBoardItemsAroundInlineThread(msgs, thread, [
      { id: "sh" },
    ]);
    assert.deepEqual(split.before.map((b) => b.id), []);
    assert.deepEqual(split.after.map((b) => b.id), ["sh"]);
  });

  it("Story Hook card then student answer → hook then chat", () => {
    const msgs: ChatItem[] = [
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "hook",
        visual: { type: "concept_story_hook", card: {} },
      },
      { id: "ans", role: "user", kind: "text", content: "guess" },
    ];
    const thread = filterInlineBoardChatMessages(msgs, "story_hook_await");
    const split = splitBoardItemsAroundInlineThread(msgs, thread, [
      { id: "sh" },
    ]);
    assert.deepEqual(split.before.map((b) => b.id), ["sh"]);
    assert.deepEqual(split.after.map((b) => b.id), []);
  });
});

describe("chronological conversation thread", () => {
  const zone0Thread: ChatItem[] = [
    {
      id: "q1",
      role: "assistant",
      kind: "text",
      content: "What keeps your heart beating...?",
    },
    { id: "a1", role: "user", kind: "text", content: "don't know" },
    {
      id: "q2",
      role: "assistant",
      kind: "text",
      content: "Hassam, when you think...",
    },
    { id: "a2", role: "user", kind: "text", content: "don't know" },
    {
      id: "q3",
      role: "assistant",
      kind: "text",
      content: "If your heart is about...",
    },
    { id: "a3", role: "user", kind: "text", content: "don't know" },
    {
      id: "act",
      role: "user",
      kind: "text",
      content: "Ready",
      rawContent: "__action:zone0_ready",
    },
  ];

  it("Q1,A1,Q2,A2,Q3,A3 renders exactly in that order", () => {
    const filtered = filterInlineBoardChatMessages(zone0Thread, "zone0_answer");
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["q1", "a1", "q2", "a2", "q3", "a3"]
    );
  });

  it("tutor feedback between Q/A remains in correct order", () => {
    const withFeedback: ChatItem[] = [
      {
        id: "q1",
        role: "assistant",
        kind: "text",
        content: "Question one?",
      },
      { id: "a1", role: "user", kind: "text", content: "answer" },
      {
        id: "fb",
        role: "assistant",
        kind: "feedback",
        message: "Nice try",
        correct: false,
      },
      {
        id: "q2",
        role: "assistant",
        kind: "text",
        content: "Question two?",
      },
      { id: "a2", role: "user", kind: "text", content: "answer 2" },
    ];
    const filtered = filterInlineBoardChatMessages(withFeedback, "zone0_answer");
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["q1", "a1", "fb", "q2", "a2"]
    );
  });

  it("DOM order tutor → student → tutor after append", () => {
    const msgs: ChatItem[] = [
      { id: "t1", role: "assistant", kind: "text", content: "Q?" },
      { id: "s1", role: "user", kind: "text", content: "A" },
      { id: "t2", role: "assistant", kind: "text", content: "Next Q?" },
    ];
    const filtered = filterInlineBoardChatMessages(msgs, "zone0_answer");
    assert.deepEqual(
      filtered.map((m) => m.role),
      ["assistant", "user", "assistant"]
    );
  });

  it("hidden actions excluded without reordering", () => {
    const filtered = filterInlineBoardChatMessages(zone0Thread, "zone0_answer");
    assert.ok(filtered.every((m) => m.id !== "act"));
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["q1", "a1", "q2", "a2", "q3", "a3"]
    );
  });

  it("omits conversational tutor text from board to avoid duplicate", () => {
    const omit = inlineConversationBoardOmitIds(zone0Thread, "zone0_answer");
    assert.ok(omit.has("q1") && omit.has("q2") && omit.has("q3"));
    assert.equal(omit.has("a1"), false);
  });

  it("story hook card stays on board; only student answers in thread", () => {
    const msgs: ChatItem[] = [
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "Hook question?",
        visual: { type: "concept_story_hook", card: {} },
      },
      { id: "ans", role: "user", kind: "text", content: "my guess" },
    ];
    assert.equal(isDurableBoardStageMessage(msgs[0]!), true);
    const filtered = filterInlineBoardChatMessages(msgs, "story_hook_await");
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["ans"]
    );
    const omit = inlineConversationBoardOmitIds(msgs, "story_hook_await");
    assert.equal(omit.has("sh"), false);
  });

  it("VTSE timeline never enters bubble thread", () => {
    const msgs: ChatItem[] = [
      {
        id: "vtse",
        role: "assistant",
        kind: "text",
        content: "timeline",
        instruction_timeline_v3: { beats: [] },
      },
      { id: "u", role: "user", kind: "text", content: "hi" },
    ];
    assert.equal(isDurableBoardStageMessage(msgs[0]!), true);
    const filtered = filterInlineBoardChatMessages(msgs, "zone0_answer");
    assert.ok(!filtered.some((m) => m.id === "vtse"));
  });

  it("clarity teachback keeps teachback_prompt bubble", () => {
    const msgs: ChatItem[] = [
      {
        id: "tb",
        role: "assistant",
        kind: "teachback_prompt",
        message: "Explain in your own words",
      },
      { id: "u", role: "user", kind: "text", content: "my explanation" },
    ];
    const filtered = filterInlineBoardChatMessages(msgs, "clarity_teachback");
    assert.deepEqual(
      filtered.map((m) => m.id),
      ["tb", "u"]
    );
  });

  it("non-chat modes return no bubbles", () => {
    assert.deepEqual(filterInlineBoardChatMessages(zone0Thread, null), []);
    assert.deepEqual(
      filterInlineBoardChatMessages(zone0Thread, "legacy_quiz"),
      []
    );
  });

  it("restore/reload still shows the same chronological history", () => {
    const restored = [...zone0Thread];
    const filtered = filterInlineBoardChatMessages(restored, "zone0_answer");
    assert.deepEqual(
      filtered.map((m) => `${m.role}:${"content" in m ? m.content : ""}`),
      [
        "assistant:What keeps your heart beating...?",
        "user:don't know",
        "assistant:Hassam, when you think...",
        "user:don't know",
        "assistant:If your heart is about...",
        "user:don't know",
      ]
    );
  });

  it("latest streamable id prefers omitted inline tutor text over empty board", () => {
    const omit = inlineConversationBoardOmitIds(zone0Thread, "zone0_answer");
    const latest = resolveLatestStreamableAssistantId(zone0Thread, [], omit);
    assert.equal(latest, "q3");
  });
});

describe("action buttons + legacy quiz", () => {
  it("action buttons show for Ready without a right column", () => {
    assert.equal(
      shouldShowBoardActionButtons(
        ui({
          flowState: "zone0_curiosity",
          buttons: [{ id: "zone0_ready", label: "I'm ready" }],
        })
      ),
      true
    );
  });

  it("legacy QuizBox still reachable under board", () => {
    assert.equal(
      shouldShowBoardQuizBox(
        ui({
          flowState: "quizzing",
          activeQuiz: { intro: "Q", question: "What?" },
        })
      ),
      true
    );
    assert.equal(
      shouldShowBoardQuizBox(
        ui({
          flowState: "zone0_curiosity",
          activeQuiz: { intro: "Q", question: "What?" },
        }),
        { zone0LearningUi: true }
      ),
      false
    );
  });
});
