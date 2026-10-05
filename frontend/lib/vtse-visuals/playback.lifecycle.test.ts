/**
 * VTSE highlight lifecycle.
 * Run: npx tsx --test lib/vtse-visuals/playback.lifecycle.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  beatNarrationText,
  charOffsetForWord,
  cueAtOffset,
  isCollapsedWordBurst,
  narrationWordAtElapsed,
  narrationWordIndexForBoardWord,
  resolveVtseHighlight,
  visualClockEvents,
  type VtseHighlightBeat,
  type VtseVisualCue,
} from "./playback";

const here = dirname(fileURLToPath(import.meta.url));

function source(rel: string): string {
  return readFileSync(join(here, "..", "..", rel), "utf8");
}

const IMAGES = [{ asset_key: "diagram" }];

function beat(
  id: string,
  narration: string,
  visual: VtseHighlightBeat["metadata"]
): VtseHighlightBeat {
  return {
    beat_id: id,
    narration_segments: [{ text: narration }],
    metadata: visual,
  };
}

function cue(charStart: number, regions: string[]): VtseVisualCue {
  return { char_start: charStart, asset_key: "diagram", region_ids: regions };
}

/** Pre-fix resolver: a missed cue replaced the highlight with an empty list. */
function legacyRegions(
  beats: VtseHighlightBeat[],
  beatId: string,
  wordIndex: number
): string[] {
  const index = beats.findIndex((item) => item.beat_id === beatId);
  let regionIds: string[] = [];
  for (let i = 0; i <= index; i += 1) {
    const visual = beats[i]?.metadata?.vtse_visual;
    if (visual?.carry) continue;
    if (!visual) {
      regionIds = [];
      continue;
    }
    const cues = visual.cues || [];
    if (i < index) {
      regionIds = cues[cues.length - 1]?.region_ids || visual.region_ids || [];
    } else if (cues.length) {
      const offset = charOffsetForWord(beatNarrationText(beats[i]), wordIndex);
      regionIds = cueAtOffset(cues, offset)?.region_ids || [];
    } else {
      regionIds = [];
    }
  }
  return regionIds;
}

test("pre-fix multi-op trace: a word-index reset turns the highlight off", () => {
  const narration = "alpha beta gamma delta epsilon zeta eta theta";
  const beats = [
    beat("beat_0002", narration, {
      vtse_visual: { asset_key: "diagram", cues: [cue(charOffsetForWord(narration, 4), ["pore"])] },
    }),
  ];
  const on = legacyRegions(beats, "beat_0002", 4);
  const off = legacyRegions(beats, "beat_0002", 0);
  const lines = [
    `beat=beat_0002 word=4 regions=${on.join(",") || "(empty)"} ${on.length ? "ON" : "OFF"}`,
    `beat=beat_0002 word=0 regions=${off.join(",") || "(empty)"} ${off.length ? "ON" : "OFF"}`,
  ];
  console.info(`[VTSE_VISUAL] pre-fix trace\n${lines.join("\n")}`);
  assert.deepEqual(on, ["pore"]);
  assert.deepEqual(off, []);
  assert.match(lines[0], /ON/);
  assert.match(lines[1], /OFF/);
});

test("one cue stays for every narration word, including index 0", () => {
  const narration = "The pore opens and then closes again today";
  const beats = [beat("beat_0001", narration, { vtse_visual: { asset_key: "diagram", cues: [cue(0, ["pore"])] } })];
  for (const word of [0, 1, 3, 8]) {
    const frame = resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "beat_0001",
      narrationWordIndex: word,
    });
    assert.deepEqual(frame?.regionIds, ["pore"]);
  }
});

test("hierarchy, clustered, linear, and cycle each hold their region for the beat", () => {
  const strategies = ["hierarchy", "clustered", "linear", "cycle"] as const;
  for (const name of strategies) {
    const beats = [0, 1, 2].map((i) =>
      beat(`beat_${i}`, `${name} step ${i} is explained here`, {
        vtse_visual: { asset_key: "diagram", cues: [cue(0, [`${name}-${i}`])] },
      })
    );
    const mid = resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "beat_1",
      narrationWordIndex: 0,
    });
    const later = resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "beat_1",
      narrationWordIndex: 6,
    });
    const next = resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "beat_2",
      narrationWordIndex: 0,
    });
    assert.deepEqual(mid?.regionIds, [`${name}-1`]);
    assert.deepEqual(later?.regionIds, [`${name}-1`]);
    assert.deepEqual(next?.regionIds, [`${name}-2`]);
  }
});

test("comparison moves left to right with no empty frame", () => {
  const narration = "Humans feel happiness inside. In contrast, robots do not feel happiness.";
  const boundary = narration.indexOf("In contrast");
  const beats = [
    beat("row", narration, {
      vtse_visual: {
        asset_key: "diagram",
        cues: [cue(0, ["left"]), cue(boundary, ["right"])],
      },
    }),
  ];
  const seen = new Set<string>();
  const words = narration.split(/\s+/);
  for (let word = 0; word < words.length; word += 1) {
    const frame = resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "row",
      narrationWordIndex: word,
    });
    assert.ok(frame && frame.regionIds.length > 0);
    seen.add(frame.regionIds[0]);
  }
  assert.deepEqual([...seen], ["left", "right"]);
  const atStart = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "row",
    narrationWordIndex: 0,
  });
  assert.deepEqual(atStart?.regionIds, ["left"]);
});

test("silent partner keeps the final comparison cue when word index is 0", () => {
  const narration = "Humans feel happiness inside. In contrast, robots do not feel happiness.";
  const boundary = narration.indexOf("In contrast");
  const beats = [
    beat("row", narration, {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["left"]), cue(boundary, ["right"])] },
    }),
    beat("silent", "\u200b", { vtse_visual: { carry: true } }),
  ];
  const frame = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "silent",
    narrationWordIndex: 0,
  });
  assert.deepEqual(frame?.regionIds, ["right"]);
  assert.equal(frame?.assetKey, "diagram");
});

test("an unbound beat clears regions and keeps the image", () => {
  const beats = [
    beat("bound", "The pore opens wide", {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["pore"])] },
    }),
    beat("plain", "A later line with no picture", undefined),
  ];
  const frame = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "plain",
    narrationWordIndex: 0,
  });
  assert.deepEqual(frame?.regionIds, []);
  assert.equal(frame?.assetKey, "diagram");
});

test("a cue that has not started yet holds the previous beat's region", () => {
  const narration = "alpha beta gamma delta epsilon zeta eta theta";
  const late = charOffsetForWord(narration, 4);
  const beats = [
    beat("earlier", "The first region stays", {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["kept"])] },
    }),
    beat("late", narration, {
      vtse_visual: { asset_key: "diagram", cues: [cue(late, ["pore"])] },
    }),
  ];
  const held = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "late",
    narrationWordIndex: 0,
  });
  const lit = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "late",
    narrationWordIndex: 4,
  });
  assert.deepEqual(held?.regionIds, ["kept"]);
  assert.deepEqual(lit?.regionIds, ["pore"]);
});

test("a checkpoint gap does not change the highlight", () => {
  const beats = [
    beat("step", "Water evaporates from the leaf", {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["leaf"])] },
    }),
  ];
  const before = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "step",
    narrationWordIndex: 2,
  });
  const duringPause = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "step",
    narrationWordIndex: 2,
  });
  assert.deepEqual(duringPause, before);
});

test("TTS off steps the narration clock instead of the collapsed board burst", () => {
  const narration = "Humans feel happiness inside. In contrast, robots do not feel happiness.";
  const boundary = narration.indexOf("In contrast");
  const beats = [
    beat("row", narration, {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["left"]), cue(boundary, ["right"])] },
    }),
  ];
  const boardCount = 4;
  const burst = Array.from({ length: boardCount }, (_, i) => i);
  assert.equal(isCollapsedWordBurst(burst, boardCount), true);
  const events = visualClockEvents(narration, 280);
  const frames = events.map((event) =>
    resolveVtseHighlight({
      beats,
      images: IMAGES,
      beatId: "row",
      narrationWordIndex: event.narrationWordIndex,
    })
  );
  assert.ok(frames.every((frame) => frame && frame.regionIds.length > 0));
  assert.deepEqual(frames[0]?.regionIds, ["left"]);
  assert.deepEqual(frames[frames.length - 1]?.regionIds, ["right"]);
  const mid = narrationWordAtElapsed(events, 0);
  assert.equal(mid, 0);
});

test("TTS on maps board progress onto narration words", () => {
  const narration = "one two three four five six seven eight";
  const narrIdx = narrationWordIndexForBoardWord(narration, 1, 2);
  assert.equal(narrIdx, 7);
  assert.notEqual(narrIdx, 1);
  const start = narrationWordIndexForBoardWord(narration, 0, 2);
  assert.equal(start, 0);
});

test("restore at the end of a comparison beat selects the right cue", () => {
  const narration = "Humans feel happiness inside. In contrast, robots do not feel happiness.";
  const boundary = narration.indexOf("In contrast");
  const beats = [
    beat("row", narration, {
      vtse_visual: { asset_key: "diagram", cues: [cue(0, ["left"]), cue(boundary, ["right"])] },
    }),
  ];
  const frame = resolveVtseHighlight({
    beats,
    images: IMAGES,
    beatId: "row",
    narrationWordIndex: Number.MAX_SAFE_INTEGER,
  });
  assert.deepEqual(frame?.regionIds, ["right"]);
  assert.equal(frame?.cueIndex, 1);
});

test("no package images produce no highlight frame", () => {
  const frame = resolveVtseHighlight({
    beats: [],
    images: [],
    beatId: null,
    narrationWordIndex: 0,
  });
  assert.equal(frame, null);
});

test("the companion does not remount on beat or word changes", () => {
  const companion = source("components/ai/timeline-v3/VtseVisualCompanion.tsx");
  assert.match(companion, /resolveVtseHighlight/);
  assert.doesNotMatch(companion, /key=\{/);
  assert.doesNotMatch(companion, /absolute bottom-3 right-3/);
});

test("playback publishes one beat and does not reset the visual clock per operation", () => {
  const view = source("components/ai/timeline-v3/ProductionTimelineRuntimeView.tsx");
  const speech = view.slice(view.indexOf("const runSpeechSyncedSegment"), view.indexOf("let cancelled"));
  assert.doesNotMatch(speech, /setVtseWordIndex\(0\)/);
  assert.match(view, /publishVtseBeat\(beat, plan\.segment\.text/);
  const legacy = view.slice(view.indexOf("async function runLegacyFrameNarration"), view.indexOf("async function runBeatOrchestratedNarration"));
  assert.doesNotMatch(legacy, /setVtseBeatId/);
  const gate = view.slice(view.indexOf("async function maybeAwaitFlowCheckpoint"), view.indexOf("for (const beat of beatsInOrder)"));
  assert.doesNotMatch(gate, /setVtse/);
  const whiteboard = source("components/ai/AIWhiteboard.tsx");
  assert.match(whiteboard, /data-whiteboard-width="column"/);
  assert.match(whiteboard, /wideVtseVisual \? "vtse-visual" : "column"/);
});
