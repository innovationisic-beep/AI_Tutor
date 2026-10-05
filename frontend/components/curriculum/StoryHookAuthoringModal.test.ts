import test from "node:test";
import assert from "node:assert/strict";

import {
  storyHookIsConfigured,
  storyHookSeedPreview,
} from "@/components/curriculum/StoryHookAuthoringModal";

test("storyHookIsConfigured detects seed or visuals", () => {
  assert.equal(
    storyHookIsConfigured({
      title: "",
      body: "",
      teacher_intent: "",
      visuals: [],
    }),
    false
  );
  assert.equal(
    storyHookIsConfigured({
      title: "Hook",
      body: "",
      teacher_intent: "",
      visuals: [],
    }),
    true
  );
  assert.equal(
    storyHookIsConfigured({
      title: "",
      body: "Once upon a leaf.",
      teacher_intent: "",
      visuals: [],
    }),
    true
  );
  assert.equal(
    storyHookIsConfigured({
      title: "",
      body: "",
      teacher_intent: "",
      visuals: [{ asset_key: "leaf", storage_key: "sk" }],
    }),
    true
  );
});

test("storyHookSeedPreview truncates cleanly", () => {
  assert.equal(storyHookSeedPreview(""), "");
  assert.equal(storyHookSeedPreview("  short seed  "), "short seed");
  const long = "a".repeat(200);
  const preview = storyHookSeedPreview(long, 40);
  assert.equal(preview.length, 40);
  assert.ok(preview.endsWith("…"));
});
