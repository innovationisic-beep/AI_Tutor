/**
 * VTSE authoring adapter. Geometry tools stay in the shared editor.
 * Run: npx tsx --test lib/vtse-visuals/authoring.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  bindingFromSlot,
  imagesToVtsePackage,
  vtsePackageToImages,
} from "./authoring";
import { listVtseAuthorSlots } from "./slots";
import type { VtseVisuals } from "../types";

const here = dirname(fileURLToPath(import.meta.url));

const saved: VtseVisuals = {
  images: [
    {
      id: "img1",
      asset_key: "diagram",
      storage_key: "abc/diagram.png",
      annotations_status: "confirmed",
      regions: [
        {
          region_id: "r1",
          label: "Pore",
          shape: "rect",
          geometry: { x: 0.1, y: 0.2, w: 0.3, h: 0.4 },
          bindings: [
            {
              slot_kind: "step",
              slot_key: "step:mix",
              slot_index: 1,
              side: "",
            },
          ],
        },
      ],
      anchors: [],
      connections: [],
    },
  ],
};

test("existing rectangle package reopens with geometry and binding", () => {
  const images = vtsePackageToImages(saved);
  const again = imagesToVtsePackage(images);
  assert.equal(again.images[0]!.regions[0]!.shape, "rect");
  assert.deepEqual(again.images[0]!.regions[0]!.geometry, {
    x: 0.1,
    y: 0.2,
    w: 0.3,
    h: 0.4,
  });
  assert.equal(again.images[0]!.regions[0]!.label, "Pore");
  assert.deepEqual(again.images[0]!.regions[0]!.bindings, saved.images[0]!.regions[0]!.bindings);
});

test("slot binding does not rename the region label", () => {
  const slots = listVtseAuthorSlots(
    {
      strategy_id: "linear_process",
      payload: { steps: [{ label: "Gather" }, { label: "Mix" }] },
    },
    "Mixing"
  );
  const mix = slots.find((slot) => slot.slot_index === 1);
  assert.ok(mix);
  const images = vtsePackageToImages(saved);
  const region = images[0]!.regions![0]!;
  const next = imagesToVtsePackage([
    {
      ...images[0]!,
      regions: [{ ...region, label: region.label, bindings: [bindingFromSlot(mix!)] }],
    },
  ]);
  assert.equal(next.images[0]!.regions[0]!.label, "Pore");
  assert.equal(next.images[0]!.regions[0]!.bindings[0]!.slot_key, "step:mix");
  assert.equal(next.images[0]!.regions[0]!.bindings[0]!.slot_index, 1);
});

test("circle and arrow chrome round-trip without becoming a highlight binding", () => {
  const images = vtsePackageToImages({
    images: [
      {
        ...saved.images[0]!,
        regions: [
          {
            ...saved.images[0]!.regions[0]!,
            shape: "ellipse",
            geometry: { cx: 0.4, cy: 0.4, rx: 0.1, ry: 0.1 },
          },
        ],
        connections: [
          {
            connection_id: "arrow_1",
            from_anchor: "arrow_1_from",
            to_anchor: "arrow_1_to",
            label: "flow",
            kind: "flow",
          },
        ],
        anchors: [
          { anchor_id: "arrow_1_from", point: { x: 0.1, y: 0.2 } },
          { anchor_id: "arrow_1_to", point: { x: 0.8, y: 0.3 } },
        ],
      },
    ],
  });
  const again = imagesToVtsePackage(images);
  assert.equal(again.images[0]!.regions[0]!.shape, "ellipse");
  assert.equal(again.images[0]!.connections?.[0]?.connection_id, "arrow_1");
  assert.equal(again.images[0]!.connections?.[0]?.kind, "flow");
  assert.equal(again.images[0]!.regions[0]!.bindings.length, 1);
});

test("VTSE authoring uses the shared editor and saves only vtse_visuals", () => {
  const modal = readFileSync(
    join(here, "..", "..", "components", "curriculum", "VtseVisualsAuthoringModal.tsx"),
    "utf8"
  );
  const editor = readFileSync(
    join(here, "..", "..", "components", "curriculum", "ImageAnnotationEditor.tsx"),
    "utf8"
  );
  assert.match(modal, /useImageAnnotation/);
  assert.match(modal, /vtse_visuals:/);
  assert.doesNotMatch(modal, /visual_teaching:/);
  assert.match(modal, /maxImages=\{MAX_VTSE_IMAGES\}/);
  assert.match(editor, /\["rectangle", "Rectangle"\]/);
  assert.match(editor, /\["square", "Square"\]/);
  assert.match(editor, /\["circle", "Circle"\]/);
  assert.match(editor, /\["arrow", "Arrow"\]/);
  assert.match(modal, /regionExtra=\{regionSlot\}/);
  assert.doesNotMatch(modal, /VTSE slot[\s\S]{0,200}label:/);
});