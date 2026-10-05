/**
 * Visual Teaching frontend contract tests (node:test, mirrors Story Hook style).
 */
import test from "node:test";
import assert from "node:assert/strict";

import { applyVisualStatePatch } from "./applyVisualState";
import { emptyVisualState } from "./types";
import { fitImageBox } from "./fitImageBox";
import { isCapabilitySupported, unsupportedIn } from "./capabilities";

test("applyVisualStatePatch: omitted field preserves", () => {
  const base = { ...emptyVisualState(), highlights: ["a"], pointer: "a" as string | null };
  const out = applyVisualStatePatch(base, { pointer: "b" });
  assert.deepEqual(out.highlights, ["a"]);
  assert.equal(out.pointer, "b");
});

test("applyVisualStatePatch: empty list clears highlights", () => {
  const base = { ...emptyVisualState(), highlights: ["a", "b"] };
  assert.deepEqual(applyVisualStatePatch(base, { highlights: [] }).highlights, []);
});

test("applyVisualStatePatch: null and empty string clear pointer", () => {
  const base = { ...emptyVisualState(), pointer: "a" as string | null };
  assert.equal(applyVisualStatePatch(base, { pointer: null }).pointer, null);
  assert.equal(applyVisualStatePatch(base, { pointer: "" }).pointer, null);
});

test("fitImageBox letterboxes wider image", () => {
  const box = fitImageBox(200, 200, 400, 200);
  assert.equal(box.width, 200);
  assert.equal(box.height, 100);
  assert.equal(box.x, 0);
  assert.equal(box.y, 50);
});

test("capabilities mirror reports unsupported", () => {
  assert.equal(isCapabilitySupported("highlights"), true);
  assert.deepEqual(unsupportedIn(["highlights", "teleport"]), ["teleport"]);
});
