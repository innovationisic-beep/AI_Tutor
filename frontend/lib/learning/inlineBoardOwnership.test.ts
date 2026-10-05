/**
 * Board ownership + bubble/thinking UX contracts (source-level).
 * Run: npx tsx --test lib/learning/inlineBoardOwnership.test.ts
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const root = join(process.cwd());

function read(rel: string): string {
  return readFileSync(join(root, rel), "utf8");
}

describe("inline chat board ownership", () => {
  it("AIWhiteboard exposes inlineChat + boardFooter slots inside surface", () => {
    const src = read("components/ai/AIWhiteboard.tsx");
    assert.match(src, /inlineChat\??:\s*ReactNode/);
    assert.match(src, /boardFooter\??:\s*ReactNode/);
    assert.match(src, /data-testid="ai-whiteboard-inline-chat-slot"/);
    assert.match(src, /data-testid="ai-whiteboard-footer-slot"/);
    assert.match(src, /data-testid="ai-whiteboard-surface"/);
    const surfaceIdx = src.indexOf('data-testid="ai-whiteboard-surface"');
    const footerIdx = src.indexOf('data-testid="ai-whiteboard-footer-slot"');
    assert.ok(surfaceIdx > 0 && footerIdx > surfaceIdx);
  });

  it("AIWhiteboard chronologically splits board around inline chat", () => {
    const src = read("components/ai/AIWhiteboard.tsx");
    assert.match(src, /timeline\?:/);
    assert.match(src, /kind: "conversation"/);
    assert.match(src, /data-timeline-episode/);
  });

  it("learn page passes InlineBoardChat into AIWhiteboard, not as sibling below", () => {
    const src = read("app/(app)/learn/[topicId]/page.tsx");
    assert.match(src, /timeline=\{whiteboardTimeline\}/);
    assert.match(src, /boardFooter=\{/);
    assert.match(src, /<InlineBoardChat/);
    assert.match(src, /showBoardComposer/);
    const wbOpen = src.indexOf("<AIWhiteboard");
    assert.ok(wbOpen > 0);
    const scratchpad = src.indexOf("<StudentScratchpadPanel", wbOpen);
    assert.ok(scratchpad > wbOpen);
    const wbBlock = src.slice(wbOpen, scratchpad);
    assert.ok(wbBlock.includes("whiteboardTimeline") || wbBlock.includes("timeline={"));
    assert.ok(
      wbBlock.includes("<InputBox") || wbBlock.includes("showBoardComposer")
    );
    // InlineBoardChat is built inside whiteboardTimeline useMemo, not after AIWhiteboard.
    const after = src.slice(scratchpad);
    assert.equal(
      after.includes("<InlineBoardChat"),
      false,
      "InlineBoardChat must not appear after AIWhiteboard closes"
    );
  });

  it("InlineBoardChat has no separate strip background / outer scroll cage", () => {
    const src = read("components/learning/InlineBoardChat.tsx");
    assert.match(src, /data-testid="inline-board-chat"/);
    assert.doesNotMatch(src, /max-h-\[min\(28vh/);
    assert.doesNotMatch(src, /border-t border-slate-200/);
    assert.doesNotMatch(src, /bg-white\/90/);
  });

  it("MessageBubble marks student right / tutor left", () => {
    const src = read("components/chat/MessageBubble.tsx");
    assert.match(src, /data-testid=\{isUser \? "bubble-student" : "bubble-tutor"\}/);
    assert.match(src, /data-align=\{isUser \? "right" : "left"\}/);
    assert.match(src, /isUser \? "justify-end" : "justify-start"/);
  });

  it("composer uses board-surface styling when compact", () => {
    const src = read("components/chat/InputBox.tsx");
    assert.match(src, /data-testid="board-composer"/);
    assert.match(src, /compact[\s\S]*bg-transparent/);
  });

  it("Thinking… sits inline left of the input, not below", () => {
    const src = read("components/chat/InputBox.tsx");
    assert.match(src, /data-testid="composer-thinking"/);
    assert.match(src, /thinkingInline/);
    // Below-row hint must skip the thinking case.
    assert.match(src, /disabledHint && !thinkingInline/);
  });

  it("InlineBoardChat maps one ordered list (no role-grouped sections)", () => {
    const src = read("components/learning/InlineBoardChat.tsx");
    assert.match(src, /messages\.map\(/);
    assert.doesNotMatch(src, /tutorMessages|studentMessages|assistantOnly|userOnly/);
  });

  it("InlineBoardChat uses WordSyncedStreaming for tutor prose TTS/word-sync", () => {
    const src = read("components/learning/InlineBoardChat.tsx");
    assert.match(src, /WordSyncedStreaming/);
    assert.match(src, /activeStreamMessageId/);
    assert.match(src, /onStreamComplete/);
    assert.match(src, /staticMode=\{!isActive\}/);
  });

  it("learn page wires inline stream completion when latest is an omitted bubble", () => {
    const src = read("app/(app)/learn/[topicId]/page.tsx");
    assert.match(src, /resolveLatestStreamableAssistantId/);
    assert.match(src, /latestStreamIsInlineBubble/);
    assert.match(src, /activeStreamMessageId=/);
    assert.match(src, /onStreamComplete=\{/);
    assert.match(src, /handleExplanationComplete\(streamId\)/);
  });
});

describe("bubble width + thinking UX", () => {
  it("AI/tutor bubble can occupy larger content-relative width (no 22rem/24rem cap)", () => {
    const src = read("components/learning/InlineBoardChat.tsx");
    assert.doesNotMatch(src, /22rem|24rem/);
    assert.match(src, /max-w-\[90%\]/);
    assert.match(src, /md:max-w-\[72%\]/);
    assert.match(src, /w-fit/);
  });

  it("student bubbles stay somewhat narrower", () => {
    const src = read("components/learning/InlineBoardChat.tsx");
    assert.match(src, /md:max-w-\[58%\]/);
  });

  it("ephemeral thinking row — not persisted into messages / useChat", () => {
    const chat = read("components/learning/InlineBoardChat.tsx");
    assert.match(chat, /TutorThinkingBubble/);
    assert.match(chat, /Tutor is thinking/);
    assert.match(chat, /testId = "inline-tutor-thinking"/);
    assert.match(chat, /loading \? <TutorThinkingBubble/);
    // Thinking copy is JSX-only, not pushed into messages array.
    assert.doesNotMatch(chat, /messages\.push|setMessages/);

    const page = read("app/(app)/learn/[topicId]/page.tsx");
    // Thinking only on the episode that owns the latest student turn.
    assert.match(page, /conversationEpisodeShowsThinking/);
    assert.match(page, /loading=\{showThinking\}/);
    assert.match(page, /shouldShowStageTransitionThinking/);
    assert.doesNotMatch(page, /loading=\{Boolean\(loading && isLastConvo\)\}/);
    assert.doesNotMatch(page, /loading=\{loading && showBoardComposer\}/);
  });

  it("conversation container keeps stable identity/key across request", () => {
    const chat = read("components/learning/InlineBoardChat.tsx");
    assert.match(chat, /data-conversation-key="inline-board-conversation"/);
    const page = read("app/(app)/learn/[topicId]/page.tsx");
    assert.match(page, /key: `convo-\$\{/);
    assert.match(page, /whiteboardTimeline/);
  });

  it("history visibility uses episode predicate, not composer-only", () => {
    const page = read("app/(app)/learn/[topicId]/page.tsx");
    assert.match(page, /buildLearnBoardTimeline/);
    assert.match(page, /whiteboardTimeline/);
    assert.match(page, /conversationOwnedAssistantTextIds/);
    assert.match(page, /timeline=\{whiteboardTimeline\}/);
  });

  it("no fake thinking message content in filter path", () => {
    const lib = read("lib/learning/inlineBoardChat.ts");
    assert.doesNotMatch(lib, /Tutor is thinking/);
    assert.doesNotMatch(lib, /kind:\s*"thinking"/);
  });

  it("VTSE stage-done gated on board timeline id, board stays wired during interrupt", () => {
    const page = read("app/(app)/learn/[topicId]/page.tsx");
    assert.match(page, /shouldCompleteVtseStageOnItem/);
    assert.match(page, /awaitVtseBoardCompletion/);
    assert.match(page, /lastDurableBoardItemId/);
  });
});
