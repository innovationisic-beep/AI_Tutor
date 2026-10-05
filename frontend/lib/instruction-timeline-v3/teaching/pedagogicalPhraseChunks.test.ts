import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  boardInkForSpeechProgress,
  completedSentenceIndexForSpeechProgress,
  joinPhraseChunks,
  pedagogicalPhraseChunks,
  splitSpokenSentences,
  visibleTextForNarrationProgress,
} from "@/lib/instruction-timeline-v3/teaching/pedagogicalPhraseChunks";

describe("pedagogicalPhraseChunks", () => {
  it("splits on clause conjunctions", () => {
    const chunks = pedagogicalPhraseChunks(
      "Humans need food and water because they are living organisms.",
    );
    assert.ok(chunks.length >= 2);
    assert.ok(chunks.join(" ").includes("because"));
  });

  it("maps narration progress to display text", () => {
    const full =
      "Humans need food and water because they are living organisms with complex needs.";
    const chunks = pedagogicalPhraseChunks(full);
    assert.ok(chunks.length >= 2);
    const partial = visibleTextForNarrationProgress(full, 0, chunks.length);
    assert.ok(partial.length < full.length);
    const complete = visibleTextForNarrationProgress(full, chunks.length - 1, chunks.length);
    assert.equal(complete, full);
  });

  it("joins phrase chunks", () => {
    assert.equal(joinPhraseChunks(["a", "b"], 1), "a b");
  });

  it("splitSpokenSentences matches sentence boundaries", () => {
    assert.deepEqual(splitSpokenSentences("Hello there. What next? Cool!"), [
      "Hello there.",
      "What next?",
      "Cool!",
    ]);
  });

  it("boardInk reveals writes only after their sentence completes", () => {
    const spoken =
      "First idea lands here. Filler transition. Second idea is durable.";
    const writes = [
      { sentenceIndex: 0, text: "First idea" },
      { sentenceIndex: 2, text: "Second idea" },
    ];
    const words = spoken.trim().split(/\s+/);
    // Mid first sentence → no write yet until sentence 0 completes
    const midFirst = completedSentenceIndexForSpeechProgress(spoken, 1, words.length);
    assert.equal(midFirst, -1);
    assert.equal(
      boardInkForSpeechProgress(spoken, writes, 1, words.length),
      "",
    );
    // After first sentence (4 words: First idea lands here.)
    const afterFirst = completedSentenceIndexForSpeechProgress(
      spoken,
      3,
      words.length,
    );
    assert.equal(afterFirst, 0);
    assert.equal(
      boardInkForSpeechProgress(spoken, writes, 3, words.length),
      "First idea",
    );
    // End → both
    assert.equal(
      boardInkForSpeechProgress(spoken, writes, words.length - 1, words.length),
      "First idea\nSecond idea",
    );
  });
});
