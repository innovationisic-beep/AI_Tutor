import test from "node:test";
import assert from "node:assert/strict";

import {
  extractTeachingKeywords,
  lineKeywordSegments,
  shouldHighlightLine,
} from "@/lib/instruction-timeline-v3/teaching/teachingKeywordHighlight";

test("extracts title-aligned science keywords", () => {
  const keywords = extractTeachingKeywords("Living things", [
    "• Living things grow",
    "• Cells divide and multiply",
    "• Nutrients are absorbed",
  ]);
  assert.ok(keywords.has("grow"));
  assert.ok(keywords.has("divide") || keywords.has("cells"));
  assert.ok(keywords.size >= 2);
  assert.ok(keywords.size <= 4);
});

test("lineKeywordSegments marks keyword tokens", () => {
  const keywords = new Set(["grow", "divide"]);
  const segments = lineKeywordSegments("• Living things grow", keywords);
  assert.ok(segments.some((s) => s.highlight && /grow/i.test(s.text)));
});

test("shouldHighlightLine waits for line completion while speaking", () => {
  assert.equal(shouldHighlightLine(0, 2, "speaking"), true);
  assert.equal(shouldHighlightLine(1, 2, "speaking"), false);
  assert.equal(shouldHighlightLine(1, 2, "stable"), true);
});
