import test from "node:test";
import assert from "node:assert/strict";

import {
  dedupeAssetKey,
  normalizeAssetKey,
  normalizeStoryHookVisualAssetKeys,
} from "@/lib/api/curriculumStructure";

test("normalizeAssetKey matches backend underscore slug convention", () => {
  assert.equal(normalizeAssetKey("Stomata Surface"), "stomata_surface");
  assert.equal(normalizeAssetKey("living thing"), "living_thing");
  assert.equal(normalizeAssetKey("living_thing"), "living_thing");
  assert.equal(normalizeAssetKey("Living-Thing!!"), "living_thing");
  assert.equal(normalizeAssetKey(""), "visual_1");
  assert.equal(normalizeAssetKey("   ", 2), "visual_3");
  assert.equal(normalizeAssetKey("a".repeat(80)).length, 64);
});

test("dedupeAssetKey appends -2 -3 like backend", () => {
  assert.equal(dedupeAssetKey("leaf", []), "leaf");
  assert.equal(dedupeAssetKey("leaf", ["leaf"]), "leaf-2");
  assert.equal(dedupeAssetKey("leaf", ["leaf", "leaf-2"]), "leaf-3");
});

test("normalizeStoryHookVisualAssetKeys dedupes and trims", () => {
  const out = normalizeStoryHookVisualAssetKeys([
    {
      asset_key: "Leaf Surface",
      storage_key: "a",
      description: "  pores  ",
      teaching_purpose: "  show  ",
    },
    {
      asset_key: "leaf_surface",
      storage_key: "b",
    },
  ]);
  assert.equal(out[0].asset_key, "leaf_surface");
  assert.equal(out[1].asset_key, "leaf_surface-2");
  assert.equal(out[0].description, "pores");
  assert.equal(out[0].teaching_purpose, "show");
});
