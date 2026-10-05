import assert from "node:assert/strict";
import test from "node:test";

import { visualTeachingDisplayText } from "./speakOnlyInk";

test("zero-write beat is speak-only (empty displayText)", () => {
  assert.equal(visualTeachingDisplayText(undefined), "");
  assert.equal(visualTeachingDisplayText([]), "");
});

test("boardWrites keep the streaming ink path", () => {
  assert.equal(
    visualTeachingDisplayText([{ text: "Pore = leaf door" }]),
    undefined
  );
});
