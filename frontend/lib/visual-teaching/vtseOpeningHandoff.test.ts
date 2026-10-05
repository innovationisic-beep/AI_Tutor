/**
 * FE contract: VTSE opening acks never append a second timeline.
 * Run: npx tsx --test lib/visual-teaching/vtseOpeningHandoff.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deriveSessionUi, flowStateFromBackend } from "../tutorFlow";
import type { TutorResponse } from "../types";

// Mirror mapResponse swallow rules without importing the whole useChat hook.
function mapBoardItems(res: TutorResponse): unknown[] {
  if (res.type === "noop") return [];
  if (res.type === "visual_teaching_sentence_ack") return [];
  if (res.type === "visual_teaching_advance_ack") return [];
  if (res.type === "vtse_opening_ack") return [];
  if (res.type === "explanation") {
    return [
      {
        kind: "text",
        content: res.message,
        instruction_timeline_v3:
          (res as { instruction_timeline_v3?: unknown }).instruction_timeline_v3 ??
          null,
      },
    ];
  }
  return [{ kind: "other", type: res.type }];
}

describe("VTSE opening handoff FE contract", () => {
  it("vtse_opening_ack appends zero board items", () => {
    const ack: TutorResponse = {
      type: "vtse_opening_ack",
      outcome: "already_starting",
      concept_index: 0,
      status: "starting",
      flow_state: "concept_vtse_opening",
    };
    assert.equal(mapBoardItems(ack).length, 0);
  });

  it("stale visual_teaching_advance_ack appends zero board items", () => {
    const ack: TutorResponse = {
      type: "visual_teaching_advance_ack",
      outcome: "already_advanced",
      scene_index: 0,
      beat_index: 0,
      status: "done",
      flow_state: "concept_vtse_opening",
    };
    assert.equal(mapBoardItems(ack).length, 0);
  });

  it("TTS-off burst of acks never creates duplicate timelines", () => {
    const burst: TutorResponse[] = [
      {
        type: "explanation",
        message: "VTSE once",
        instruction_timeline_v3: { beats: [{ id: "1" }] },
      } as TutorResponse,
      {
        type: "vtse_opening_ack",
        outcome: "already_starting",
        flow_state: "concept_vtse_opening",
      },
      {
        type: "visual_teaching_advance_ack",
        outcome: "already_advanced",
        status: "done",
        flow_state: "concept_vtse_opening",
      },
      {
        type: "vtse_opening_ack",
        outcome: "already_started",
        flow_state: "explaining",
      },
    ];
    const board = burst.flatMap(mapBoardItems);
    const timelines = board.filter(
      (b) =>
        b &&
        typeof b === "object" &&
        "instruction_timeline_v3" in b &&
        (b as { instruction_timeline_v3: unknown }).instruction_timeline_v3 != null
    );
    assert.equal(timelines.length, 1);
  });

  it("deriveSessionUi keeps concept_vtse_opening on ack", () => {
    const ui = deriveSessionUi(
      {
        type: "vtse_opening_ack",
        outcome: "already_starting",
        flow_state: "concept_vtse_opening",
      },
      {
        flowState: "concept_visual_teaching",
        currentConcept: "heart",
        buttons: [],
        activeQuiz: null,
        lessonProgress: null,
        currentZone: 1,
        sessionMeta: null,
      }
    );
    assert.equal(ui.flowState, "concept_vtse_opening");
  });

  it("flowStateFromBackend maps concept_vtse_opening", () => {
    assert.equal(
      flowStateFromBackend("concept_vtse_opening", null),
      "concept_vtse_opening"
    );
  });
});
