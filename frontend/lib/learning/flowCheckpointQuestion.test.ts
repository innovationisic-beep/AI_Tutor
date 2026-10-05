import assert from "node:assert/strict";
import test from "node:test";

import { acceptedCheckpointClarification } from "./flowCheckpointContinue";

test("teachback retry is not checkpoint clarification text", () => {
  assert.equal(
    acceptedCheckpointClarification({
      type: "teachback_retry",
      message: "I think you haven't quite got what I was teaching",
    }),
    null,
  );
});

test("stale checkpoint question is not shown as clarification", () => {
  assert.equal(
    acceptedCheckpointClarification({
      type: "flow_checkpoint_clarification",
      outcome: "stale",
      message: "",
    }),
    null,
  );
});

test("accepted clarification text is shown", () => {
  assert.equal(
    acceptedCheckpointClarification({
      type: "flow_checkpoint_clarification",
      message: "The pore opens so gases can move.",
    }),
    "The pore opens so gases can move.",
  );
});
