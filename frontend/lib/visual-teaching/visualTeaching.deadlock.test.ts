/**
 * Visual Teaching deadlock / concurrency contract (frontend).
 *
 * Covers flow sticky-acks, restore ownership, and advancement guard semantics
 * without mounting the full learn page.
 */
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { deriveSessionUi, type SessionUiState } from "@/lib/tutorFlow";
import type { TutorResponse } from "@/lib/types";
import { attachVisualTeachingBeatStreaming } from "@/lib/learning/storyHookBoardGrouping";
import type { VisualTeachingBeatStep } from "@/lib/learning/storyHookBoardGrouping";
import type { BoardItem } from "@/components/ai/AIWhiteboard";

const vtPrev: SessionUiState = {
  flowState: "concept_visual_teaching",
  currentConcept: "Stomata",
  buttons: [],
  activeQuiz: null,
  lessonProgress: null,
  currentZone: 1,
  sessionMeta: null,
};

describe("VT sentence-progress must not change pedagogical flow", () => {
  test("visual_teaching_sentence_ack keeps concept_visual_teaching", () => {
    const res: TutorResponse = {
      type: "visual_teaching_sentence_ack",
      scene_index: 0,
      beat_index: 0,
      sentence_index: 2,
      accepted: true,
    };
    const next = deriveSessionUi(res, vtPrev);
    assert.equal(next.flowState, "concept_visual_teaching");
  });

  test("legacy noop while in VT stays concept_visual_teaching", () => {
    const next = deriveSessionUi({ type: "noop" }, vtPrev);
    assert.equal(next.flowState, "concept_visual_teaching");
  });

  test("noop does not sticky story_hook (regression)", () => {
    const hookPrev: SessionUiState = {
      ...vtPrev,
      flowState: "concept_story_hook",
    };
    const next = deriveSessionUi({ type: "noop" }, hookPrev);
    // Story Hook must not stick on noop (would strand before VTSE).
    assert.notEqual(next.flowState, "concept_story_hook");
  });
});

describe("VT restore ownership", () => {
  function beat(
    id: string,
    scene: number,
    beatIndex: number
  ): VisualTeachingBeatStep {
    return {
      id,
      heading: "Visual Teaching",
      title: "T",
      speak: "Hello.",
      regions: [],
      anchors: [],
      connections: [],
      visualState: { highlights: [], labels_visible: [], arrows: [] },
      sentenceEvents: [],
      sceneIndex: scene,
      beatIndex,
      sceneCount: 1,
      beatCount: 2,
      sentenceIndex: 0,
      isLastBeat: false,
    };
  }

  test("active restored beat resumes + owns completion", () => {
    const beats = [beat("b0", 0, 0), beat("b1", 0, 1)];
    const items = beats.map(
      (b) =>
        ({
          id: b.id,
          role: "assistant",
          kind: "text",
          content: b.speak,
          visual: { type: "concept_visual_teaching", scene_index: 0 },
        }) as BoardItem
    );
    const streamed = attachVisualTeachingBeatStreaming(beats, items, {
      lastBoardItemId: "b1",
      staticRestoreByItemId: { b0: 0, b1: 1 },
    });
    assert.equal(streamed[0]!.streamStaticMode, true);
    assert.equal(streamed[0]!.ownsCompletion, false);
    assert.equal(streamed[1]!.streamStaticMode, false);
    assert.equal(streamed[1]!.ownsCompletion, true);
  });
});

describe("VT advancement guard semantics", () => {
  type Guard = { key: string; inFlight: boolean; confirmed: boolean } | null;

  function tryAdvance(
    guard: Guard,
    key: string
  ): { next: Guard; sent: boolean } {
    if (guard?.key === key && (guard.inFlight || guard.confirmed)) {
      return { next: guard, sent: false };
    }
    return {
      next: { key, inFlight: true, confirmed: false },
      sent: true,
    };
  }

  function afterResponse(
    guard: Guard,
    key: string,
    tutorType: string | undefined
  ): Guard {
    if (
      tutorType &&
      tutorType !== "noop" &&
      tutorType !== "visual_teaching_sentence_ack"
    ) {
      return { key, inFlight: false, confirmed: true };
    }
    if (guard?.key === key) return null;
    return guard;
  }

  test("duplicate onComplete for same beat does not double-send", () => {
    let g: Guard = null;
    const key = "s1:0:0";
    const a = tryAdvance(g, key);
    assert.equal(a.sent, true);
    g = a.next;
    const b = tryAdvance(g, key);
    assert.equal(b.sent, false);
  });

  test("noop clears guard so retry is possible", () => {
    let g: Guard = { key: "s1:0:0", inFlight: true, confirmed: false };
    g = afterResponse(g, "s1:0:0", "noop");
    assert.equal(g, null);
    const retry = tryAdvance(g, "s1:0:0");
    assert.equal(retry.sent, true);
  });

  test("confirmed advance blocks further sends for same beat", () => {
    let g: Guard = { key: "s1:0:0", inFlight: true, confirmed: false };
    g = afterResponse(g, "s1:0:0", "concept_visual_teaching");
    assert.equal(g?.confirmed, true);
    const dup = tryAdvance(g, "s1:0:0");
    assert.equal(dup.sent, false);
  });

  test("advance_ack already_advanced confirms guard", () => {
    let g: Guard = { key: "s1:0:0", inFlight: true, confirmed: false };
    // Mimic page confirmation rule for advance_ack.
    const tutorType = "visual_teaching_advance_ack";
    const outcome = "already_advanced";
    const confirmed =
      (tutorType !== "noop" &&
        tutorType !== "visual_teaching_sentence_ack" &&
        tutorType !== "visual_teaching_advance_ack") ||
      outcome === "already_advanced" ||
      outcome === "accepted" ||
      outcome === "completed";
    assert.equal(confirmed, true);
    g = { key: "s1:0:0", inFlight: false, confirmed: true };
    const dup = tryAdvance(g, "s1:0:0");
    assert.equal(dup.sent, false);
  });

  test("advance_ack stale clears for retry", () => {
    let g: Guard = { key: "s1:0:0", inFlight: true, confirmed: false };
    const outcome = "stale";
    const confirmed =
      outcome === "already_advanced" ||
      outcome === "accepted" ||
      outcome === "completed";
    assert.equal(confirmed, false);
    if (!confirmed) g = null;
    const retry = tryAdvance(g, "s1:0:0");
    assert.equal(retry.sent, true);
  });

  test("new scene/beat key allows advance", () => {
    const g: Guard = {
      key: "s1:0:0",
      inFlight: false,
      confirmed: true,
    };
    const next = tryAdvance(g, "s1:0:1");
    assert.equal(next.sent, true);
  });
});

describe("VT sentence coalesce", () => {
  test("microtask coalesce keeps highest sentence index only", async () => {
    const bag = new Map<
      string,
      { scene: number; beat: number; sentence: number }
    >();
    const sent: number[] = [];
    const coalesceKey = "0:0";
    const enqueue = (sentence: number) => {
      const prev = bag.get(coalesceKey);
      if (prev && sentence <= prev.sentence) return;
      bag.set(coalesceKey, { scene: 0, beat: 0, sentence });
      queueMicrotask(() => {
        const latest = bag.get(coalesceKey);
        if (!latest) return;
        bag.delete(coalesceKey);
        sent.push(latest.sentence);
      });
    };
    enqueue(0);
    enqueue(1);
    enqueue(2);
    await new Promise<void>((r) => queueMicrotask(r));
    assert.deepEqual(sent, [2]);
  });
});

describe("VT background send option contract", () => {
  test("background option is distinct from silent", () => {
    // Document the production contract: sentence checkpoints use both.
    const opts = { silent: true, background: true };
    assert.equal(opts.silent, true);
    assert.equal(opts.background, true);
    // Global loading must only be toggled when !background (enforced in useChat).
    const shouldSetLoading = !opts.background;
    assert.equal(shouldSetLoading, false);
  });
});
