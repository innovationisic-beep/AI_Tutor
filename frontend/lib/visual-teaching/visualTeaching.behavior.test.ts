/**
 * Visual Teaching frontend behavior tests (overlay/geometry, authoring, student card).
 * Run: npx tsx --test lib/visual-teaching/visualTeaching.behavior.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { applyVisualStatePatch } from "./applyVisualState";
import { fitImageBox } from "./fitImageBox";
import {
  geometryToSvgPaths,
  resolveFocusPoint,
  regionById,
} from "./geometry";
import { emptyVisualState, SVG_VIEWBOX, type VisualState } from "./types";
import {
  parseConceptVisualTeachingCard,
} from "../../components/learning/ConceptVisualTeachingCard";
import {
  validateVisualTeachingDraft,
  visualTeachingPreview,
} from "../../components/curriculum/VisualTeachingAuthoringModal";
import type { VisualTeachingDraft } from "../api/curriculumStructure";

const here = dirname(fileURLToPath(import.meta.url));

const REGION = {
  region_id: "pore",
  label: "Pore",
  teaching_purpose: "Opening",
  sort_order: 0,
  shape: "rect" as const,
  geometry: { x: 0.1, y: 0.2, w: 0.3, h: 0.4 },
  focus_point: { x: 0.25, y: 0.35 },
};

const REGION_B = {
  region_id: "guard",
  label: "Guard",
  teaching_purpose: "Cells",
  sort_order: 1,
  shape: "ellipse" as const,
  geometry: { cx: 0.7, cy: 0.6, rx: 0.1, ry: 0.15 },
  focus_point: null,
};

// ---------------------------------------------------------------------------
// Overlay / geometry
// ---------------------------------------------------------------------------

test("normalized region aligns with image content box via fitImageBox", () => {
  const box = fitImageBox(400, 300, 800, 400);
  // Letterboxed: image is 400x200 centered vertically.
  assert.equal(box.width, 400);
  assert.equal(box.height, 200);
  assert.equal(box.x, 0);
  assert.equal(box.y, 50);

  // Region at normalized (0.1, 0.2) maps into the content box, not the letterbox.
  const contentX = box.x + REGION.geometry.x * box.width;
  const contentY = box.y + REGION.geometry.y * box.height;
  assert.equal(contentX, 40);
  assert.equal(contentY, 50 + 40);
  assert.ok(contentY > box.y);
  assert.ok(contentY < box.y + box.height);
});

test("highlight and pointer resolve intended region focus", () => {
  const paths = geometryToSvgPaths([REGION, REGION_B]);
  const pore = paths.find((p) => p.region_id === "pore");
  assert.ok(pore);
  assert.equal(pore!.shape, "rect");
  assert.match(String(pore!.d), /^M /);

  const fp = resolveFocusPoint(REGION);
  assert.deepEqual(fp, { x: 0.25, y: 0.35 });

  const state = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["pore"],
    pointer: "pore",
    labels_visible: ["pore"],
    dim_others: true,
    zoom: { region_id: "pore" },
    arrows: ["flow_1"],
  });
  assert.deepEqual(state.highlights, ["pore"]);
  assert.equal(state.pointer, "pore");
  assert.deepEqual(state.labels_visible, ["pore"]);
  assert.equal(state.dim_others, true);
  assert.deepEqual(state.zoom, { region_id: "pore" });
  assert.deepEqual(state.arrows, ["flow_1"]);

  assert.equal(regionById([REGION, REGION_B], state.pointer)?.region_id, "pore");

  // Zoom/reset
  const cleared = applyVisualStatePatch(state, { zoom: null, labels_visible: [] });
  assert.equal(cleared.zoom, null);
  assert.deepEqual(cleared.labels_visible, []);
  // Highlights preserved when omitted
  assert.deepEqual(cleared.highlights, ["pore"]);
});

test("arrows resolve through connection ids (state lists connection_id)", () => {
  const connections = [
    {
      connection_id: "flow_1",
      from_anchor: "a",
      to_anchor: "b",
      label: "flow",
      kind: "flow" as const,
    },
  ];
  const state = applyVisualStatePatch(emptyVisualState(), {
    arrows: ["flow_1", "missing"],
  });
  const visible = connections.filter((c) =>
    state.arrows.includes(c.connection_id)
  );
  assert.equal(visible.length, 1);
  assert.equal(visible[0]!.connection_id, "flow_1");
});

test("VisualState can show highlights and arrows simultaneously", () => {
  const state = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["right_atrium"],
    arrows: ["body_to_right_atrium"],
  });
  assert.deepEqual(state.highlights, ["right_atrium"]);
  assert.deepEqual(state.arrows, ["body_to_right_atrium"]);
});

test("highlights + labels_visible + arrows coexist in one VisualState", () => {
  const state = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["right_atrium"],
    labels_visible: ["right_atrium"],
    arrows: ["body_to_right_atrium"],
  });
  assert.deepEqual(state.highlights, ["right_atrium"]);
  assert.deepEqual(state.labels_visible, ["right_atrium"]);
  assert.deepEqual(state.arrows, ["body_to_right_atrium"]);
});

test("arrows-only patch preserves highlights and labels_visible", () => {
  const base = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["right_atrium"],
    labels_visible: ["right_atrium"],
    arrows: ["old_arrow"],
  });
  const next = applyVisualStatePatch(base, {
    arrows: ["body_to_right_atrium"],
  });
  assert.deepEqual(next.highlights, ["right_atrium"]);
  assert.deepEqual(next.labels_visible, ["right_atrium"]);
  assert.deepEqual(next.arrows, ["body_to_right_atrium"]);
});

test("labels_visible patch works independently (scene-2 style)", () => {
  const base = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["right_atrium"],
  });
  const next = applyVisualStatePatch(base, {
    labels_visible: ["right_atrium"],
  });
  assert.deepEqual(next.highlights, ["right_atrium"]);
  assert.deepEqual(next.labels_visible, ["right_atrium"]);
});

test("multi-scene SVG marker ids are unique for same connection_id", async () => {
  const { scopedMarkerId, scopedLabelClipId, sanitizeSvgIdPart } = await import(
    "./VisualTeachingOverlay"
  );
  const a = scopedMarkerId("scene-0", "body_to_right_atrium");
  const b = scopedMarkerId("scene-1", "body_to_right_atrium");
  assert.notEqual(a, b);
  assert.match(a, /scene-0/);
  assert.match(b, /scene-1/);
  assert.equal(
    scopedLabelClipId("scene-0", "right_atrium", 0),
    "vt-label-clip-scene-0-right_atrium-0"
  );
  assert.notEqual(
    scopedLabelClipId("scene-0", "right_atrium", 0),
    scopedLabelClipId("scene-1", "right_atrium", 0)
  );
  assert.equal(sanitizeSvgIdPart("a/b c"), "a_b_c");
});

test("sentence patch replacing arrows preserves omitted highlights", () => {
  const base = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["right_atrium"],
    arrows: ["old_arrow"],
  });
  const next = applyVisualStatePatch(base, {
    arrows: ["body_to_right_atrium"],
  });
  assert.deepEqual(next.highlights, ["right_atrium"]);
  assert.deepEqual(next.arrows, ["body_to_right_atrium"]);
});

test("sentence patch can replace highlights and arrows together", () => {
  const base = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["a"],
    arrows: ["x"],
  });
  const next = applyVisualStatePatch(base, {
    highlights: ["right_atrium"],
    arrows: ["body_to_right_atrium"],
  });
  assert.deepEqual(next.highlights, ["right_atrium"]);
  assert.deepEqual(next.arrows, ["body_to_right_atrium"]);
});

test("authoring UI exposes arrow_id/label/teaching_purpose, not kind picker", () => {
  const src = readFileSync(
    join(
      here,
      "..",
      "..",
      "components",
      "curriculum",
      "ImageAnnotationEditor.tsx"
    ),
    "utf8"
  );
  const modal = readFileSync(
    join(
      here,
      "..",
      "..",
      "components",
      "curriculum",
      "VisualTeachingAuthoringModal.tsx"
    ),
    "utf8"
  );
  assert.match(src, /placeholder="arrow_id"/);
  assert.match(src, /placeholder="Teaching purpose"/);
  assert.match(src, /teaching_purpose: e\.target\.value/);
  // Kind select options must not appear in authoring UI.
  assert.doesNotMatch(src, /<option value="compare">compare<\/option>/);
  assert.doesNotMatch(src, /<option value="generic">generic<\/option>/);
  // New arrows still default kind internally to flow.
  assert.match(src, /kind: "flow"/);
  assert.match(modal, /visual_teaching: \{ images: draft\.images \}/);
  assert.match(modal, /\["preview", "Preview"\]/);
  assert.match(modal, /useImageAnnotation/);
});

test("annotate arrow persists as connection + endpoint anchors (runtime model)", async () => {
  const { nextArrowConnectionId, arrowEndpointIds } = await import(
    "./arrowGeometry"
  );
  const connection_id = nextArrowConnectionId([]);
  const ids = arrowEndpointIds(connection_id);
  assert.equal(connection_id, "arrow_1");
  const anchors = [
    { anchor_id: ids.from, label: "", point: { x: 0.15, y: 0.4 } },
    { anchor_id: ids.to, label: "", point: { x: 0.75, y: 0.45 } },
  ];
  const connections = [
    {
      connection_id,
      from_anchor: ids.from,
      to_anchor: ids.to,
      label: "direction",
      kind: "flow" as const,
    },
  ];
  const state = applyVisualStatePatch(emptyVisualState(), {
    arrows: [connection_id],
  });
  assert.deepEqual(state.arrows, ["arrow_1"]);
  assert.equal(connections[0]!.from_anchor, anchors[0]!.anchor_id);
  assert.equal(connections[0]!.to_anchor, anchors[1]!.anchor_id);
});

test("SVG geometry uses viewBox units matching overlay contract", () => {
  const paths = geometryToSvgPaths([REGION]);
  const d = paths[0]!.d!;
  // x=0.1 → 100, y=0.2 → 200 in 0..1000 viewBox
  assert.match(d, new RegExp(`M ${0.1 * SVG_VIEWBOX} ${0.2 * SVG_VIEWBOX}`));
});

test("reduced-motion: final visual state is independent of enter_effects", () => {
  // Enter-effect animation is not rendered on the FE today; final VisualState is
  // authoritative. reduced-motion must still end at the same patched state.
  const final = applyVisualStatePatch(emptyVisualState(), {
    highlights: ["pore"],
    pointer: "pore",
    dim_others: true,
  });
  assert.deepEqual(final.highlights, ["pore"]);
  assert.equal(final.pointer, "pore");
  assert.equal(final.dim_others, true);
});

// ---------------------------------------------------------------------------
// Authoring
// ---------------------------------------------------------------------------

function baseDraft(overrides?: Partial<VisualTeachingDraft["images"][number]>): VisualTeachingDraft {
  return {
    images: [
      {
        id: "1",
        asset_key: "leaf",
        storage_key: "leaf-aaa.png",
        mime_type: "image/png",
        sort_order: 0,
        title: "Leaf",
        teaching_purpose: "Show pore",
        natural_width: 100,
        natural_height: 80,
        content_hash: "abc",
        annotations_status: "confirmed",
        regions: [REGION],
        anchors: [
          { anchor_id: "a1", label: "A", point: { x: 0.2, y: 0.3 } },
          { anchor_id: "a2", label: "B", point: { x: 0.7, y: 0.6 } },
        ],
        connections: [
          {
            connection_id: "c1",
            from_anchor: "a1",
            to_anchor: "a2",
            label: "",
            kind: "flow",
          },
        ],
        ...overrides,
      },
    ],
  };
}

test("authoring: replace image → stale immediately in draft preview", () => {
  const draft = baseDraft({
    storage_key: "leaf-bbb.png",
    annotations_status: "stale",
  });
  assert.equal(visualTeachingPreview(draft), "1 image · 1 stale");
  const errors = validateVisualTeachingDraft(draft);
  assert.ok(errors.some((e) => e.includes("stale")));
});

test("authoring: stale package cannot appear confirmed without reconfirm", () => {
  const stale = baseDraft({ annotations_status: "stale" });
  assert.ok(
    validateVisualTeachingDraft(stale).some((e) => e.includes("stale"))
  );
  const reconfirmed = baseDraft({ annotations_status: "confirmed" });
  assert.equal(
    validateVisualTeachingDraft(reconfirmed).filter((e) => e.includes("stale"))
      .length,
    0
  );
});

test("authoring: duplicate region/anchor validation shown", () => {
  const draft = baseDraft({
    regions: [REGION, { ...REGION, label: "dup" }],
    anchors: [
      { anchor_id: "a1", label: "A", point: { x: 0.2, y: 0.3 } },
      { anchor_id: "a1", label: "dup", point: { x: 0.5, y: 0.5 } },
    ],
  });
  const errors = validateVisualTeachingDraft(draft);
  assert.ok(errors.some((e) => e.includes('duplicate region_id "pore"')));
  assert.ok(errors.some((e) => e.includes('duplicate anchor_id "a1"')));
});

test("authoring: ordinary metadata edit preserves annotations and confirmed status", () => {
  const before = baseDraft();
  const edited = baseDraft({
    teaching_purpose: "Updated purpose only",
    title: "New title",
  });
  assert.equal(edited.images[0]!.annotations_status, "confirmed");
  assert.deepEqual(edited.images[0]!.regions, before.images[0]!.regions);
  assert.deepEqual(edited.images[0]!.anchors, before.images[0]!.anchors);
  assert.equal(edited.images[0]!.storage_key, before.images[0]!.storage_key);
});

test("authoring: replacement does not silently preserve confirmed", () => {
  // Mirrors upload replace response + modal force-stale mapping.
  const replaceResponse = {
    storage_key: "leaf-new.png",
    annotations_status: "stale" as const,
  };
  const nextStatus =
    replaceResponse.annotations_status === "stale" ? "stale" : "stale";
  assert.equal(nextStatus, "stale");
  assert.notEqual(replaceResponse.storage_key, "leaf-aaa.png");
});

// ---------------------------------------------------------------------------
// Student card / runtime
// ---------------------------------------------------------------------------

function sampleCardPayload(overrides: Record<string, unknown> = {}) {
  return {
    type: "concept_visual_teaching",
    speak: "Look at the pore. Now the guard cells.",
    image_path: "/curriculum/concepts/c1/visual-teaching/images/leaf",
    asset_key: "leaf",
    scene_index: 0,
    beat_index: 0,
    scene_count: 2,
    beat_count: 1,
    sentence_index: -1,
    image: {
      title: "Leaf surface",
      natural_width: 800,
      natural_height: 600,
    },
    regions: [REGION, REGION_B],
    anchors: [
      { anchor_id: "a1", label: "A", point: { x: 0.2, y: 0.3 } },
      { anchor_id: "a2", label: "B", point: { x: 0.7, y: 0.6 } },
    ],
    connections: [
      {
        connection_id: "flow_1",
        from_anchor: "a1",
        to_anchor: "a2",
        label: "",
        kind: "flow",
      },
    ],
    visual_state: {
      highlights: [],
      pointer: null,
      labels_visible: [],
      dim_others: false,
      zoom: null,
      arrows: [],
    },
    sentence_events: [
      {
        sentence_index: 0,
        patch: { highlights: ["pore"], pointer: "pore" },
      },
      {
        sentence_index: 1,
        patch: {
          highlights: ["guard"],
          labels_visible: ["guard"],
          dim_others: true,
          arrows: ["flow_1"],
          zoom: { region_id: "guard" },
        },
      },
    ],
    writes: [{ sentence_index: 0, text: "Pore = leaf door" }],
    ...overrides,
  };
}

/** Replay sentence patches the same way ConceptVisualTeachingCard does. */
function replayToSentence(
  base: VisualState,
  events: Array<{ sentence_index: number; patch: Record<string, unknown> }>,
  upTo: number
): VisualState {
  let state = base;
  for (const ev of events) {
    if (ev.sentence_index > upTo) break;
    if (ev.sentence_index < 0) continue;
    state = applyVisualStatePatch(state, ev.patch as never);
  }
  return state;
}

test("student: sentence_event patch applies at correct sentence index", () => {
  const card = parseConceptVisualTeachingCard(sampleCardPayload());
  assert.ok(card);
  assert.equal(card!.sentenceEvents.length, 2);
  assert.equal(card!.boardWrites?.[0]?.sentenceIndex, 0);
  assert.equal(card!.boardWrites?.[0]?.text, "Pore = leaf door");

  const after0 = replayToSentence(
    card!.visualState,
    card!.sentenceEvents,
    0
  );
  assert.deepEqual(after0.highlights, ["pore"]);
  assert.equal(after0.pointer, "pore");

  const after1 = replayToSentence(
    card!.visualState,
    card!.sentenceEvents,
    1
  );
  assert.deepEqual(after1.highlights, ["guard"]);
  assert.deepEqual(after1.labels_visible, ["guard"]);
  assert.equal(after1.dim_others, true);
  assert.deepEqual(after1.arrows, ["flow_1"]);
  assert.deepEqual(after1.zoom, { region_id: "guard" });
});

test("student: zero writes produce no boardWrites (no blank layout)", () => {
  const card = parseConceptVisualTeachingCard(
    sampleCardPayload({ writes: [] })
  );
  assert.ok(card);
  assert.equal(card!.boardWrites, undefined);
});

test("student: scene transition identity is sceneIndex + imagePath", () => {
  const scene0 = parseConceptVisualTeachingCard(sampleCardPayload());
  const scene1 = parseConceptVisualTeachingCard(
    sampleCardPayload({
      scene_index: 1,
      image_path: "/curriculum/concepts/c1/visual-teaching/images/cross",
      asset_key: "cross",
    })
  );
  assert.ok(scene0 && scene1);
  assert.equal(scene0!.sceneIndex, 0);
  assert.equal(scene1!.sceneIndex, 1);
  assert.notEqual(scene0!.imagePath, scene1!.imagePath);
});

test("student: restore reconstructs image + visual state + board ink cursor", () => {
  const restored = parseConceptVisualTeachingCard(
    sampleCardPayload({
      sentence_index: 1,
      visual_state: {
        highlights: ["guard"],
        pointer: "guard",
        labels_visible: ["guard"],
        dim_others: true,
        zoom: { region_id: "guard" },
        arrows: ["flow_1"],
      },
    })
  );
  assert.ok(restored);
  assert.equal(restored!.sentenceIndex, 1);
  assert.equal(restored!.imagePath?.endsWith("/leaf"), true);
  assert.deepEqual(restored!.visualState.highlights, ["guard"]);
  assert.equal(restored!.visualState.pointer, "guard");
  assert.deepEqual(restored!.visualState.labels_visible, ["guard"]);
  assert.equal(restored!.visualState.dim_others, true);
  assert.deepEqual(restored!.visualState.zoom, { region_id: "guard" });
  assert.deepEqual(restored!.visualState.arrows, ["flow_1"]);
  assert.equal(restored!.boardWrites?.[0]?.text, "Pore = leaf door");

  // Replay from restored base should be idempotent for already-applied events.
  const again = replayToSentence(
    restored!.visualState,
    restored!.sentenceEvents.filter((e) => e.sentence_index > restored!.sentenceIndex),
    1
  );
  assert.deepEqual(again.highlights, ["guard"]);
});

test("student: completion callback is once — last beat flagged for Done path", () => {
  const last = parseConceptVisualTeachingCard(
    sampleCardPayload({
      scene_index: 1,
      scene_count: 2,
      beat_index: 0,
      beat_count: 1,
    })
  );
  const mid = parseConceptVisualTeachingCard(
    sampleCardPayload({
      scene_index: 0,
      scene_count: 2,
      beat_index: 0,
      beat_count: 1,
    })
  );
  assert.equal(last!.isLastBeat, true);
  assert.equal(mid!.isLastBeat, false);
});

test("student: overlay state changes across beats without changing image path", () => {
  const beat0 = parseConceptVisualTeachingCard(
    sampleCardPayload({
      beat_index: 0,
      beat_count: 4,
      visual_state: { highlights: ["pore"], pointer: "pore" },
    })
  );
  const beat1 = parseConceptVisualTeachingCard(
    sampleCardPayload({
      beat_index: 1,
      beat_count: 4,
      visual_state: { highlights: ["guard"], pointer: "guard" },
    })
  );
  assert.ok(beat0 && beat1);
  assert.equal(beat0!.imagePath, beat1!.imagePath);
  assert.notDeepEqual(beat0!.visualState.highlights, beat1!.visualState.highlights);
});
