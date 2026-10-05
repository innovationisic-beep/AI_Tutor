import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { BoardItem } from "@/components/ai/AIWhiteboard";
import {
  attachStoryHookStepStreaming,
  attachVisualTeachingBeatStreaming,
  groupWhiteboardSegments,
  storyHookRunHeading,
  storyHookRunTitle,
  storyHookStepsFromItems,
} from "@/lib/learning/storyHookBoardGrouping";

function hookItem(
  id: string,
  opts: {
    title?: string;
    body?: string;
    image_path?: string;
    content?: string;
    note?: string;
    writing_mode?: "legacy" | "notes";
    spoken_text?: string;
    writes?: Array<{ sentence_index: number; text: string }>;
  } = {}
): BoardItem {
  const title = opts.title ?? "Leaf pores";
  const body = opts.body ?? "";
  const content = (opts.content ?? body) || "\u00a0";
  return {
    id,
    type: "text",
    content,
    visual: {
      type: "concept_story_hook",
      card: {
        kind: "story_hook",
        heading: "STORY HOOK",
        title,
        body,
        description: body,
        ...(opts.note !== undefined ? { note: opts.note } : {}),
        ...(opts.writing_mode ? { writing_mode: opts.writing_mode } : {}),
        ...(opts.spoken_text ? { spoken_text: opts.spoken_text } : {}),
        ...(opts.writes ? { writes: opts.writes } : {}),
        ...(opts.image_path
          ? { image_path: opts.image_path, image_alt: body || title }
          : {}),
      },
    },
  };
}

function proseItem(id: string, content: string): BoardItem {
  return { id, type: "text", content, visual: null };
}

function vtseItem(id: string): BoardItem {
  return {
    id,
    type: "text",
    content: "Compare living and non-living",
    instruction_timeline_v3: { beats: [] } as BoardItem["instruction_timeline_v3"],
    planner_source: "timeline_v3_from_cir_v1",
    visual: null,
  };
}

test("multiple narration steps → one story_hook_run segment", () => {
  const items = [
    hookItem("a", { body: "Once upon a leaf." }),
    hookItem("b", { body: "The pores open at dawn." }),
    hookItem("c", { body: "They close when dry." }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].kind, "story_hook_run");
  if (segments[0].kind !== "story_hook_run") return;
  assert.equal(segments[0].items.length, 3);
  assert.deepEqual(
    segments[0].steps.map((s) => s.body),
    ["Once upon a leaf.", "The pores open at dawn.", "They close when dry."]
  );
  assert.equal(storyHookRunHeading(segments[0].steps), "STORY HOOK");
  assert.equal(storyHookRunTitle(segments[0].steps), "Leaf pores");
});

test("narration + visual + narration → one card run in order", () => {
  const items = [
    hookItem("n1", { body: "Look closer." }),
    hookItem("v1", {
      body: "Stomata on the surface",
      image_path: "/curriculum/concepts/c1/story-hook/visuals/stomata_surface",
    }),
    hookItem("n2", { body: "Air slips through those mouths." }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].kind, "story_hook_run");
  if (segments[0].kind !== "story_hook_run") return;
  assert.equal(segments[0].steps.length, 3);
  assert.ok(segments[0].steps[1].imagePath?.includes("stomata_surface"));
  assert.equal(segments[0].steps[0].body, "Look closer.");
  assert.equal(segments[0].steps[2].body, "Air slips through those mouths.");
});

test("question + follow-up reply stay in the same Story Hook card", () => {
  const items = [
    hookItem("q", { body: "Why close the pores?" }),
    hookItem("reply", { body: "Good — water is the trade-off." }),
    hookItem("fin", { body: "And that is how plants breathe." }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].kind, "story_hook_run");
  if (segments[0].kind !== "story_hook_run") return;
  assert.equal(segments[0].steps.length, 3);
  assert.equal(segments[0].steps[1].body, "Good — water is the trade-off.");
});

test("finish does not create another segment/card", () => {
  const items = [
    hookItem("n", { body: "Narration" }),
    hookItem("finish", { body: "Final line" }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].kind, "story_hook_run");
  if (segments[0].kind !== "story_hook_run") return;
  assert.equal(segments[0].items.map((i) => i.id).join(","), "n,finish");
});

test("next VTSE/other stage appears outside Story Hook card", () => {
  const items = [
    hookItem("h1", { body: "Hook start" }),
    hookItem("h2", { body: "Hook end" }),
    vtseItem("vtse-1"),
    proseItem("p1", "Later prose"),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 3);
  assert.equal(segments[0].kind, "story_hook_run");
  assert.equal(segments[1].kind, "item");
  assert.equal(segments[2].kind, "item");
  if (segments[0].kind === "story_hook_run") {
    assert.equal(segments[0].items.length, 2);
  }
  if (segments[1].kind === "item") {
    assert.equal(segments[1].item.id, "vtse-1");
  }
  if (segments[2].kind === "item") {
    assert.equal(segments[2].item.id, "p1");
  }
});

test("no duplicate steps after identical re-group (React refresh)", () => {
  const items = [
    hookItem("a", { body: "One" }),
    hookItem("b", { body: "Two" }),
  ];
  const once = groupWhiteboardSegments(items);
  const twice = groupWhiteboardSegments(items);
  assert.deepEqual(
    once.map((s) =>
      s.kind === "story_hook_run"
        ? { kind: s.kind, ids: s.steps.map((x) => x.id) }
        : { kind: s.kind, id: s.item.id }
    ),
    twice.map((s) =>
      s.kind === "story_hook_run"
        ? { kind: s.kind, ids: s.steps.map((x) => x.id) }
        : { kind: s.kind, id: s.item.id }
    )
  );
  const steps = storyHookStepsFromItems([...items, items[0]]);
  assert.deepEqual(
    steps.map((s) => s.id),
    ["a", "b"]
  );
});

test("non-consecutive story hooks form separate cards", () => {
  const items = [
    hookItem("h1", { body: "First concept hook" }),
    proseItem("mid", "Something else"),
    hookItem("h2", { title: "Other hook", body: "Second concept hook" }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 3);
  assert.equal(segments[0].kind, "story_hook_run");
  assert.equal(segments[1].kind, "item");
  assert.equal(segments[2].kind, "story_hook_run");
});

test("attachStoryHookStepStreaming: narration uses board content for WordSyncedStreaming", () => {
  const items = [
    hookItem("a", { body: "Once upon a leaf." }),
    hookItem("b", { body: "The pores open." }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "b",
  });
  assert.equal(streamed.length, 2);
  assert.equal(streamed[0].streamText, "Once upon a leaf.");
  assert.equal(streamed[1].streamText, "The pores open.");
  assert.equal(streamed[0].streamStaticMode, false);
  assert.equal(streamed[1].streamStaticMode, false);
  assert.equal(streamed[0].ownsCompletion, false);
  assert.equal(streamed[1].ownsCompletion, true);
});

test("attachStoryHookStepStreaming: narration + visual + narration keep stream order", () => {
  const items = [
    hookItem("n1", { body: "Look closer." }),
    hookItem("v1", {
      body: "Stomata on the surface",
      image_path: "/curriculum/concepts/c1/story-hook/visuals/stomata_surface",
    }),
    hookItem("n2", { body: "Air slips through." }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "n2",
  });
  assert.deepEqual(
    streamed.map((s) => ({
      id: s.id,
      text: s.streamText,
      image: Boolean(s.imagePath),
      owns: s.ownsCompletion,
    })),
    [
      { id: "n1", text: "Look closer.", image: false, owns: false },
      { id: "v1", text: "Stomata on the surface", image: true, owns: false },
      { id: "n2", text: "Air slips through.", image: false, owns: true },
    ]
  );
});

test("attachStoryHookStepStreaming: question + follow-up both stream; only latest owns completion", () => {
  const items = [
    hookItem("q", { body: "Why close the pores?" }),
    hookItem("reply", { body: "Water is the trade-off." }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "reply",
  });
  assert.equal(streamed[0].streamText, "Why close the pores?");
  assert.equal(streamed[1].streamText, "Water is the trade-off.");
  assert.equal(streamed[0].ownsCompletion, false);
  assert.equal(streamed[1].ownsCompletion, true);
});

test("attachStoryHookStepStreaming: rerender / advance does not flip past steps to staticMode", () => {
  const items = [
    hookItem("a", { body: "One" }),
    hookItem("b", { body: "Two" }),
    hookItem("c", { body: "Three" }),
  ];
  const steps = storyHookStepsFromItems(items);
  const whileB = attachStoryHookStepStreaming(steps.slice(0, 2), items.slice(0, 2), {
    lastBoardItemId: "b",
  });
  const whileC = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "c",
  });
  // Past steps keep identical streamText + staticMode=false so WordSyncedStreaming
  // effect deps stay stable (no cancelSpeech / duplicate speak).
  assert.equal(whileC[0].streamText, whileB[0].streamText);
  assert.equal(whileC[0].streamStaticMode, false);
  assert.equal(whileC[1].streamText, whileB[1].streamText);
  assert.equal(whileC[1].streamStaticMode, false);
  assert.equal(whileC[0].ownsCompletion, false);
  assert.equal(whileC[1].ownsCompletion, false);
  assert.equal(whileC[2].ownsCompletion, true);
});

test("attachStoryHookStepStreaming: restore → staticMode (immediate full reveal)", () => {
  const items = [hookItem("a", { body: "Restored narration" })];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
    staticRestoreByItemId: { a: -1 },
  });
  assert.equal(streamed[0].streamStaticMode, true);
  assert.equal(streamed[0].ownsCompletion, false);
});

test("ConceptStoryHookCard uses WordSyncedStreaming (not static body dump)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const cardPath = join(
    here,
    "../../components/learning/ConceptStoryHookCard.tsx"
  );
  const src = readFileSync(cardPath, "utf8");
  assert.match(src, /WordSyncedStreaming/);
  assert.match(src, /streamText|streamStaticMode/);
  assert.doesNotMatch(src, /<p[^>]*>\{\s*step\.body\s*\}<\/p>/);
});

test("WordSyncedStreaming cancel/unmount contract still calls cancelSpeech", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const wssPath = join(here, "../../components/ai/WordSyncedStreaming.tsx");
  const src = readFileSync(wssPath, "utf8");
  assert.match(src, /speakWithPhraseChunkSync/);
  assert.match(src, /cancelSpeech\(\)/);
  assert.match(src, /staticMode/);
  assert.match(src, /displayText/);
  assert.match(src, /boardWrites/);
  assert.match(src, /boardInkForSpeechProgress/);
  assert.match(src, /visibleTextForNarrationProgress/);
  // Zero-ink / pre-first-write: no empty layout <p>
  assert.match(src, /Pre-first-write/);
  assert.match(src, /!String\(revealSource\)\.trim\(\)/);
});

test("notes mode: streamText is spoken; displayText is concise note", () => {
  const items = [
    hookItem("a", {
      body: "Stomata = tiny leaf gates",
      content: "Imagine a leaf with hundreds of tiny gates.",
      writing_mode: "notes",
      note: "Stomata = tiny leaf gates",
      spoken_text: "Imagine a leaf with hundreds of tiny gates.",
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  assert.equal(steps[0].writingMode, "notes");
  assert.equal(steps[0].body, "Stomata = tiny leaf gates");
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].streamText, "Imagine a leaf with hundreds of tiny gates.");
  assert.equal(streamed[0].displayText, "Stomata = tiny leaf gates");
});

test("notes mode with writes: boardWrites attached for sentence-anchored reveal", () => {
  const items = [
    hookItem("a", {
      body: "Stomata = tiny leaf gates",
      content:
        "Imagine a leaf with hundreds of tiny gates. The plant opens them for carbon dioxide.",
      writing_mode: "notes",
      note: "Stomata = tiny leaf gates",
      spoken_text:
        "Imagine a leaf with hundreds of tiny gates. The plant opens them for carbon dioxide.",
      writes: [{ sentence_index: 0, text: "Stomata = tiny leaf gates" }],
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  assert.ok(steps[0].boardWrites);
  assert.equal(steps[0].boardWrites![0].sentenceIndex, 0);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].boardWrites![0].text, "Stomata = tiny leaf gates");
});

test("notes mode empty writes: speak-only displayText and card collapses chrome", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const cardPath = join(here, "../../components/learning/ConceptStoryHookCard.tsx");
  const cardSrc = readFileSync(cardPath, "utf8");
  assert.match(cardSrc, /hasAnyVisibleContent/);
  assert.match(cardSrc, /Zero visible board content/);
  assert.match(cardSrc, /sr-only/);

  const items = [
    hookItem("a", {
      body: "",
      content: "Now here is the interesting part.",
      writing_mode: "notes",
      note: "",
      spoken_text: "Now here is the interesting part.",
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].displayText, "");
  assert.equal(streamed[0].boardWrites, undefined);
});

test("notes mode empty writes with image: card still has visible content path", () => {
  const items = [
    hookItem("a", {
      body: "",
      content: "Look at this leaf.",
      writing_mode: "notes",
      note: "",
      spoken_text: "Look at this leaf.",
      image_path: "/media/leaf.png",
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  assert.ok(steps[0].imagePath);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].displayText, "");
  assert.ok(streamed[0].imagePath);
});

test("notes mode: empty note → speak-only displayText", () => {
  const items = [
    hookItem("a", {
      body: "",
      content: "Now here is the interesting part.",
      writing_mode: "notes",
      note: "",
      spoken_text: "Now here is the interesting part.",
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].streamText, "Now here is the interesting part.");
  assert.equal(streamed[0].displayText, "");
});

test("legacy mode: displayText omitted so spoken text is revealed", () => {
  const items = [
    hookItem("a", {
      body: "Legacy spoken line on the card.",
      writing_mode: "legacy",
    }),
  ];
  const steps = storyHookStepsFromItems(items);
  const streamed = attachStoryHookStepStreaming(steps, items, {
    lastBoardItemId: "a",
  });
  assert.equal(streamed[0].streamText, "Legacy spoken line on the card.");
  assert.equal(streamed[0].displayText, undefined);
});

function vtBeatItem(
  id: string,
  opts: {
    scene_index?: number;
    beat_index?: number;
    asset_key?: string;
    speak?: string;
    highlights?: string[];
    image_path?: string;
  } = {}
): BoardItem {
  const scene = opts.scene_index ?? 0;
  const beat = opts.beat_index ?? 0;
  const asset = opts.asset_key ?? "heart_anatomy";
  return {
    id,
    type: "text",
    content: opts.speak ?? `Beat ${beat}`,
    visual: {
      type: "concept_visual_teaching",
      speak: opts.speak ?? `Beat ${beat}`,
      image_path:
        opts.image_path ??
        `/curriculum/concepts/c1/visual-teaching/images/${asset}`,
      asset_key: asset,
      scene_index: scene,
      beat_index: beat,
      scene_count: 2,
      beat_count: 4,
      sentence_index: -1,
      image: { title: asset, natural_width: 800, natural_height: 600 },
      regions: [],
      anchors: [],
      connections: [],
      visual_state: {
        highlights: opts.highlights ?? [],
        pointer: null,
        labels_visible: [],
        dim_others: false,
        zoom: null,
        arrows: [],
      },
      sentence_events: [],
      writes: [],
    },
  };
}

test("VT: 4 beats on same scene → exactly 1 visual_teaching_scene segment", () => {
  const items = [
    vtBeatItem("b0", { beat_index: 0, highlights: ["right_atrium"] }),
    vtBeatItem("b1", { beat_index: 1, highlights: ["right_ventricle"] }),
    vtBeatItem("b2", { beat_index: 2, highlights: ["left_atrium"] }),
    vtBeatItem("b3", { beat_index: 3, highlights: ["left_ventricle"] }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].kind, "visual_teaching_scene");
  if (segments[0].kind !== "visual_teaching_scene") return;
  assert.equal(segments[0].items.length, 4);
  assert.equal(segments[0].beats.length, 4);
  const paths = new Set(segments[0].beats.map((b) => b.imagePath));
  assert.equal(paths.size, 1, "all beats share one image path");
  assert.deepEqual(
    segments[0].beats.map((b) => b.visualState.highlights),
    [
      ["right_atrium"],
      ["right_ventricle"],
      ["left_atrium"],
      ["left_ventricle"],
    ]
  );
});

test("VT: scene 2 starts a new segment (image swap once)", () => {
  const items = [
    vtBeatItem("s0b0", { scene_index: 0, beat_index: 0, asset_key: "heart" }),
    vtBeatItem("s0b1", { scene_index: 0, beat_index: 1, asset_key: "heart" }),
    vtBeatItem("s1b0", {
      scene_index: 1,
      beat_index: 0,
      asset_key: "lungs",
      image_path: "/curriculum/concepts/c1/visual-teaching/images/lungs",
    }),
    vtBeatItem("s1b1", {
      scene_index: 1,
      beat_index: 1,
      asset_key: "lungs",
      image_path: "/curriculum/concepts/c1/visual-teaching/images/lungs",
    }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 2);
  assert.equal(segments[0].kind, "visual_teaching_scene");
  assert.equal(segments[1].kind, "visual_teaching_scene");
  if (
    segments[0].kind !== "visual_teaching_scene" ||
    segments[1].kind !== "visual_teaching_scene"
  ) {
    return;
  }
  assert.equal(segments[0].beats.length, 2);
  assert.equal(segments[1].beats.length, 2);
  assert.equal(segments[0].beats[0]!.sceneIndex, 0);
  assert.equal(segments[1].beats[0]!.sceneIndex, 1);
  assert.notEqual(
    segments[0].beats[0]!.imagePath,
    segments[1].beats[0]!.imagePath
  );
});

test("VT: restore mid-scene still one segment with correct latest visual state", () => {
  const items = [
    vtBeatItem("b0", { beat_index: 0, highlights: ["a"] }),
    vtBeatItem("b1", { beat_index: 1, highlights: ["b"] }),
    vtBeatItem("b2", { beat_index: 2, highlights: ["c"] }),
  ];
  const segments = groupWhiteboardSegments(items);
  assert.equal(segments.length, 1);
  if (segments[0].kind !== "visual_teaching_scene") return;
  const streamed = attachVisualTeachingBeatStreaming(segments[0].beats, items, {
    lastBoardItemId: "b2",
    staticRestoreByItemId: { b0: 0, b1: 0, b2: 1 },
  });
  assert.equal(streamed.length, 3);
  assert.deepEqual(streamed[2]!.visualState.highlights, ["c"]);
  // Active (last) restored beat resumes live TTS and owns completion — not a static dead end.
  assert.equal(streamed[2]!.streamStaticMode, false);
  assert.equal(streamed[2]!.ownsCompletion, true);
  assert.equal(streamed[0]!.streamStaticMode, true);
  assert.equal(streamed[1]!.streamStaticMode, true);
  // Only one image identity across the restored scene run.
  assert.equal(new Set(streamed.map((b) => b.imagePath)).size, 1);
});
