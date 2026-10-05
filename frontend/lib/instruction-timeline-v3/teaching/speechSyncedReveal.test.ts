import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  advanceSpeechRevealForNarrationChunk,
  createSpeechRevealState,
  resolveSpeechDisplayText,
  stabilizeSpeechReveal,
} from "@/lib/instruction-timeline-v3/teaching/speechSyncedReveal";

describe("speechSyncedReveal", () => {
  it("starts pending with empty visible text", () => {
    const s = createSpeechRevealState("node_1", "Hello world example.");
    assert.equal(s.phase, "pending");
    assert.equal(s.visibleText, "");
  });

  it("advances visible text with narration chunks", () => {
    let s = createSpeechRevealState("node_1", "Humans need food and water because they are living.");
    s = advanceSpeechRevealForNarrationChunk(s, 0, 2, 100);
    assert.equal(s.phase, "speaking");
    assert.ok(s.visibleText.length > 0);
    s = advanceSpeechRevealForNarrationChunk(s, 1, 2, 200);
    assert.equal(s.visibleText, s.fullText);
  });

  it("stabilizes to full text", () => {
    let s = createSpeechRevealState("node_1", "Done.");
    s = stabilizeSpeechReveal(s, 300);
    assert.equal(s.phase, "stable");
    assert.equal(s.visibleText, "Done.");
  });

  it("resolveSpeechDisplayText returns full text when disabled", () => {
    const r = resolveSpeechDisplayText("Full.", undefined, false);
    assert.equal(r.visibleText, "Full.");
  });
});
