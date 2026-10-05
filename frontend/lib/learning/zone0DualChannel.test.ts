/**
 * Zone 0 dual-channel (speech vs written note) — FE mapping + wiring checks.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { normalizeTutorResponse } from "@/lib/api";
import { boardTurnToChatItem } from "@/lib/sessionRestore";
import type { AskQuestionApiBody } from "@/lib/types";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "../..");

test("normalize: notes mode passes writing_mode + display_text", () => {
  const raw: AskQuestionApiBody = {
    answer: "Warm spoken paragraphs about the student reply.",
    type: "zone0_curiosity",
    message: "Warm spoken paragraphs about the student reply.",
    writing_mode: "notes",
    display_text: "Ready when you are",
    buttons: [{ id: "zone0_ready", label: "I'm ready — let's go" }],
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "zone0_curiosity");
  if (res.type !== "zone0_curiosity") return;
  assert.equal(res.writing_mode, "notes");
  assert.equal(res.display_text, "Ready when you are");
  assert.equal(res.message, "Warm spoken paragraphs about the student reply.");
});

test("normalize: notes mode passes writes from visual", () => {
  const raw: AskQuestionApiBody = {
    answer: "Light matters for plants. Ready when you like.",
    type: "zone0_curiosity",
    message: "Light matters for plants. Ready when you like.",
    writing_mode: "notes",
    display_text: "Light fuels growth",
    writes: [{ sentence_index: 0, text: "Light fuels growth" }],
    visual: {
      type: "zone0_display",
      writing_mode: "notes",
      display_text: "Light fuels growth",
      writes: [{ sentence_index: 0, text: "Light fuels growth" }],
    },
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "zone0_curiosity");
  if (res.type !== "zone0_curiosity") return;
  assert.ok(res.writes);
  assert.equal(res.writes![0].sentence_index, 0);
  assert.equal(res.writes![0].text, "Light fuels growth");
});

test("normalize: notes mode from visual when top-level omitted", () => {
  const raw: AskQuestionApiBody = {
    answer: "Spoken only path.",
    type: "zone0_curiosity",
    message: "Spoken only path.",
    visual: {
      type: "zone0_display",
      writing_mode: "notes",
      display_text: "",
    },
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "zone0_curiosity");
  if (res.type !== "zone0_curiosity") return;
  assert.equal(res.writing_mode, "notes");
  assert.equal(res.display_text, "");
});

test("normalize: question turn omits dual-channel (legacy)", () => {
  const raw: AskQuestionApiBody = {
    answer: "What do plants take from the air?",
    type: "zone0_curiosity",
    message: "What do plants take from the air?",
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "zone0_curiosity");
  if (res.type !== "zone0_curiosity") return;
  assert.equal(res.writing_mode, undefined);
  assert.equal(res.display_text, undefined);
  assert.equal(res.message, "What do plants take from the air?");
});

test("restore: board turn visual → writingMode + displayText on ChatItem", () => {
  const item = boardTurnToChatItem({
    turn_index: 3,
    content: "Full spoken after-curiosity reply.",
    visual: {
      type: "zone0_display",
      writing_mode: "notes",
      display_text: "Ready when you are",
    },
    response_type: "zone0_curiosity",
    created_at: new Date().toISOString(),
  });
  assert.equal(item.role, "assistant");
  if (item.role !== "assistant" || item.kind !== "text") return;
  assert.equal(item.writingMode, "notes");
  assert.equal(item.displayText, "Ready when you are");
  assert.equal(item.content, "Full spoken after-curiosity reply.");
});

test("restore: speak-only empty note", () => {
  const item = boardTurnToChatItem({
    turn_index: 4,
    content: "Spoken paragraphs with nothing durable to write.",
    visual: {
      type: "zone0_display",
      writing_mode: "notes",
      display_text: "",
    },
    response_type: "zone0_curiosity",
    created_at: new Date().toISOString(),
  });
  assert.equal(item.role, "assistant");
  if (item.role !== "assistant" || item.kind !== "text") return;
  assert.equal(item.writingMode, "notes");
  assert.equal(item.displayText, "");
});

test("AIWhiteboard legacy prose passes displayText for notes mode", () => {
  const src = readFileSync(
    join(root, "components/ai/AIWhiteboard.tsx"),
    "utf8"
  );
  assert.match(src, /writingMode === "notes"|notesMode/);
  assert.match(src, /displayText/);
  assert.match(src, /WordSyncedStreaming/);
});

test("AIWhiteboard notes with no ink uses zero-layout TTS wrapper", () => {
  const src = readFileSync(
    join(root, "components/ai/AIWhiteboard.tsx"),
    "utf8"
  );
  assert.match(src, /notesNoInk/);
  assert.match(src, /isNotesSpeakOnlyBoardItem/);
  assert.match(src, /layoutVisible/);
  assert.match(src, /priorVisible/);
  // Speak-only path: sr-only wrapper, no ResponseDivider for invisible rows
  assert.match(src, /Speak-only notes prose/);
  assert.match(src, /showDivider/);
});

test("isNotesSpeakOnlyBoardItem and storyHookStreamHasVisibleLayout", async () => {
  const { isNotesSpeakOnlyBoardItem, storyHookStreamHasVisibleLayout } =
    await import("@/components/ai/AIWhiteboard");

  assert.equal(
    isNotesSpeakOnlyBoardItem({
      id: "1",
      type: "text",
      content: "Spoken only.",
      writingMode: "notes",
      displayText: "",
    }),
    true
  );
  assert.equal(
    isNotesSpeakOnlyBoardItem({
      id: "2",
      type: "text",
      content: "Spoken.",
      writingMode: "notes",
      displayText: "Ink here",
    }),
    false
  );
  assert.equal(
    isNotesSpeakOnlyBoardItem({
      id: "3",
      type: "text",
      content: "Question text?",
    }),
    false
  );
  assert.equal(
    storyHookStreamHasVisibleLayout([
      {
        id: "a",
        heading: "STORY HOOK",
        title: "T",
        body: "",
        streamText: "Hello there.",
        displayText: "",
        streamStaticMode: false,
        ownsCompletion: true,
      },
    ]),
    false
  );
  assert.equal(
    storyHookStreamHasVisibleLayout([
      {
        id: "b",
        heading: "STORY HOOK",
        title: "T",
        body: "Note",
        streamText: "Hello there.",
        displayText: "Note",
        streamStaticMode: false,
        ownsCompletion: true,
      },
    ]),
    true
  );
});

test("restore: board turn visual with writes → boardWrites on ChatItem", () => {
  const item = boardTurnToChatItem({
    turn_index: 5,
    content: "Light matters for plants. Ready when you like.",
    visual: {
      type: "zone0_display",
      writing_mode: "notes",
      display_text: "Light fuels growth",
      writes: [{ sentence_index: 0, text: "Light fuels growth" }],
    },
    response_type: "zone0_curiosity",
    created_at: new Date().toISOString(),
  });
  assert.equal(item.role, "assistant");
  if (item.role !== "assistant" || item.kind !== "text") return;
  assert.equal(item.writingMode, "notes");
  assert.ok(item.boardWrites);
  assert.equal(item.boardWrites![0].sentenceIndex, 0);
  assert.equal(item.boardWrites![0].text, "Light fuels growth");
});

test("normalize: cluster_curiosity_feedback notes mode", () => {
  const raw: AskQuestionApiBody = {
    answer: "Warm appreciation paragraphs.",
    type: "cluster_curiosity_feedback",
    message: "Warm appreciation paragraphs.",
    writing_mode: "notes",
    display_text: "Curiosity before facts",
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "cluster_curiosity_feedback");
  if (res.type !== "cluster_curiosity_feedback") return;
  assert.equal(res.writing_mode, "notes");
  assert.equal(res.display_text, "Curiosity before facts");
});

test("normalize: zone0_mirror notes mode", () => {
  const raw: AskQuestionApiBody = {
    answer: "Warm mirror spoken text.",
    type: "zone0_mirror",
    message: "Warm mirror spoken text.",
    writing_mode: "notes",
    display_text: "Garden sunlight spark",
  };
  const res = normalizeTutorResponse(raw);
  assert.equal(res.type, "zone0_mirror");
  if (res.type !== "zone0_mirror") return;
  assert.equal(res.writing_mode, "notes");
  assert.equal(res.display_text, "Garden sunlight spark");
});

test("learn page auto-sends zone0_mirror_done after TTS", () => {
  const src = readFileSync(
    join(root, "app/(app)/learn/[topicId]/page.tsx"),
    "utf8"
  );
  assert.match(src, /zone0_mirror_done/);
  assert.match(src, /flowState === "zone0_mirror"/);
  // Question states still early-return (no auto-quiz).
  const idx = src.indexOf("handleExplanationComplete");
  // Slice must cover VT early-exit + Zone 0 pauses (VT block grew the function head).
  const slice = src.slice(idx, idx + 9000);
  assert.match(slice, /zone0_anchor/);
  assert.match(slice, /zone0_prereq/);
  assert.match(slice, /zone0_curiosity/);
  assert.match(slice, /concept_visual_teaching/);
});
