/**
 * Board thinking ownership + flow-checkpoint presentation.
 * Run: npx tsx --test lib/learning/boardThinking.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ChatItem } from "@/hooks/useChat";
import {
  classifyBoardLoadingKind,
  shouldShowStageTransitionThinking,
} from "./boardThinking";
import {
  buildLearnBoardTimeline,
  conversationEpisodeShowsThinking,
} from "./learnBoardTimeline";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = join(process.cwd());

describe("classifyBoardLoadingKind", () => {
  it("student reply → conversation thinking", () => {
    assert.equal(classifyBoardLoadingKind("photosynthesis", {}), "conversation");
  });

  it("story_hook_done → stage_transition", () => {
    assert.equal(
      classifyBoardLoadingKind("__action:story_hook_done", { silent: true }),
      "stage_transition"
    );
  });

  it("concept_vtse_stage_done → stage_transition", () => {
    assert.equal(
      classifyBoardLoadingKind("__action:concept_vtse_stage_done", {
        silent: true,
      }),
      "stage_transition"
    );
  });

  it("flow_checkpoint_pause → none (no thinking)", () => {
    assert.equal(
      classifyBoardLoadingKind('__action:flow_checkpoint_pause|["A","B"]', {
        silent: true,
      }),
      "none"
    );
  });

  it("flow_checkpoint_continue → none", () => {
    assert.equal(
      classifyBoardLoadingKind("__action:flow_checkpoint_continue", {
        silent: true,
      }),
      "none"
    );
  });

  it("background → none", () => {
    assert.equal(
      classifyBoardLoadingKind("__action:visual_teaching_sentence:0:0:1", {
        silent: true,
        background: true,
      }),
      "none"
    );
  });

  it("omitFromMessages (popup Q&A) → none", () => {
    assert.equal(
      classifyBoardLoadingKind("Why do stomata open?", {
        silent: true,
        omitFromMessages: true,
      }),
      "none"
    );
  });

  it("silent free-text without omit → none (not conversation tip)", () => {
    assert.equal(
      classifyBoardLoadingKind("Why?", { silent: true }),
      "none"
    );
  });
});

describe("thinking priority", () => {
  it("conversation thinking wins over stage-transition", () => {
    assert.equal(
      shouldShowStageTransitionThinking({
        loadingKind: "stage_transition",
        conversationThinkingActive: true,
      }),
      false
    );
    assert.equal(
      shouldShowStageTransitionThinking({
        loadingKind: "stage_transition",
        conversationThinkingActive: false,
      }),
      true
    );
  });

  it("ack loadingKind none → no stage thinking", () => {
    assert.equal(
      shouldShowStageTransitionThinking({
        loadingKind: "none",
        conversationThinkingActive: false,
      }),
      false
    );
  });

  it("student tip + conversation kind → episode thinking; not stage", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q?" },
      { id: "a1", role: "user", kind: "text", content: "ans" },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    const convo = tl[0]!;
    assert.equal(
      conversationEpisodeShowsThinking(convo, msgs, true, "conversation"),
      true
    );
    assert.equal(
      conversationEpisodeShowsThinking(convo, msgs, true, "stage_transition"),
      false
    );
    assert.equal(
      shouldShowStageTransitionThinking({
        loadingKind: "stage_transition",
        conversationThinkingActive: conversationEpisodeShowsThinking(
          convo,
          msgs,
          true,
          "conversation"
        ),
      }),
      false
    );
  });

  it("story hook done while board tip → stage thinking at bottom, not in old convo", () => {
    const msgs: ChatItem[] = [
      { id: "q1", role: "assistant", kind: "text", content: "Q?" },
      { id: "a1", role: "user", kind: "text", content: "ans" },
      {
        id: "sh",
        role: "assistant",
        kind: "text",
        content: "hook done",
        visual: { type: "concept_story_hook", card: {} },
      },
    ];
    const tl = buildLearnBoardTimeline(msgs);
    const kind = classifyBoardLoadingKind("__action:story_hook_done", {
      silent: true,
    });
    assert.equal(kind, "stage_transition");
    let convoThinking = false;
    for (const seg of tl) {
      if (conversationEpisodeShowsThinking(seg, msgs, true, kind)) {
        convoThinking = true;
      }
    }
    assert.equal(convoThinking, false);
    assert.equal(
      shouldShowStageTransitionThinking({
        loadingKind: kind,
        conversationThinkingActive: convoThinking,
      }),
      true
    );
  });
});

describe("flow checkpoint popup ownership (source)", () => {
  it("popup submit uses omitFromMessages", () => {
    const src = readFileSync(
      join(root, "lib/learning/useFlowCheckpointController.ts"),
      "utf8"
    );
    assert.match(src, /omitFromMessages:\s*true/);
  });

  it("useChat skips appending assistants when omitFromMessages", () => {
    const src = readFileSync(join(root, "hooks/useChat.ts"), "utf8");
    assert.match(src, /omitFromMessages/);
    assert.match(src, /if\s*\(!omitFromMessages\)\s*\{/);
    assert.match(src, /setMessages\(\(prev\)\s*=>\s*\[\.\.\.prev,\s*\.\.\.assistants\]\)/);
  });

  it("mapResponse still swallows flow_checkpoint_clarification", () => {
    const src = readFileSync(join(root, "hooks/useChat.ts"), "utf8");
    assert.match(
      src,
      /if\s*\(res\.type\s*===\s*"flow_checkpoint_clarification"\)\s*return\s*\[\]/
    );
  });

  it("mapResponse swallows flow_checkpoint_continue_ack", () => {
    const src = readFileSync(join(root, "hooks/useChat.ts"), "utf8");
    assert.match(
      src,
      /if\s*\(res\.type\s*===\s*"flow_checkpoint_continue_ack"\)\s*return\s*\[\]/
    );
  });

  it("continue awaits ack before resume (no fire-and-forget)", () => {
    const src = readFileSync(
      join(root, "lib/learning/useFlowCheckpointController.ts"),
      "utf8"
    );
    assert.match(src, /isFlowCheckpointContinueAck/);
    assert.match(src, /await sendMessage/);
    assert.doesNotMatch(
      src,
      /void sendMessage\(sessionId,\s*"__action:flow_checkpoint_continue"/
    );
  });

  it("learn page appends stage-transition thinking slot", () => {
    const src = readFileSync(
      join(root, "app/(app)/learn/[topicId]/page.tsx"),
      "utf8"
    );
    assert.match(src, /shouldShowStageTransitionThinking/);
    assert.match(src, /stage-transition-thinking/);
    assert.match(src, /loadingKind/);
  });
});
