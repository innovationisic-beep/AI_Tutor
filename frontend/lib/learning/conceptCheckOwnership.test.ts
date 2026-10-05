import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  protectConceptCheckMeta,
  resolveConceptCheckStem,
  shouldShowConceptCheckQuestion,
} from "@/lib/learning/conceptCheckOwnership";
import { deriveSessionUi } from "@/lib/tutorFlow";
import type { TutorSessionMeta } from "@/lib/types";

function baseMeta(over: Partial<TutorSessionMeta> = {}): TutorSessionMeta {
  return {
    zone: 1,
    cluster_index: 0,
    total_clusters: 1,
    concept_index: 0,
    total_concepts: 3,
    ...over,
  };
}

describe("conceptCheckOwnership", () => {
  it("shows stem when Concept Check is active with prompt", () => {
    const meta = baseMeta({
      concept_questions_active: true,
      micro_interaction_prompt: "What is blood flow?",
      micro_quiz_hold: 0,
    });
    assert.equal(shouldShowConceptCheckQuestion(meta), true);
    assert.equal(resolveConceptCheckStem(meta), "What is blood flow?");
  });

  it("does not fabricate a question when inactive or empty", () => {
    assert.equal(
      shouldShowConceptCheckQuestion(
        baseMeta({ concept_questions_active: true, micro_quiz_hold: 1 }),
      ),
      false,
    );
    assert.equal(
      shouldShowConceptCheckQuestion(
        baseMeta({ concept_questions_active: false }),
      ),
      false,
    );
  });

  it("keeps Q1 after late continue_ack wipe", () => {
    const prev = baseMeta({
      concept_questions_active: true,
      micro_quiz_hold: 1,
      micro_interaction_prompt: "What is step 1?",
      concept_question_index: 0,
      concept_question_type: "mcq",
      concept_question_options: ["A", "B"],
      concept_teaching_await_vtse_done: 0,
    });
    const incoming = baseMeta({
      concept_questions_active: true,
      micro_quiz_hold: 0,
      concept_teaching_await_vtse_done: 1,
      flow_checkpoint_pending: false,
    });
    const protectedMeta = protectConceptCheckMeta(prev, incoming, {
      type: "flow_checkpoint_continue_ack",
    });
    assert.ok(protectedMeta);
    assert.equal(protectedMeta!.micro_interaction_prompt, "What is step 1?");
    assert.equal(protectedMeta!.micro_quiz_hold, 1);
    assert.equal(protectedMeta!.concept_questions_active, true);
    assert.equal(protectedMeta!.concept_teaching_await_vtse_done, 0);
  });

  it("keeps Q1 after late active-session style stale meta", () => {
    const prev = baseMeta({
      concept_questions_active: true,
      micro_quiz_hold: 1,
      micro_interaction_prompt: "Name one chamber.",
      concept_teaching_await_vtse_done: 0,
    });
    const incoming = baseMeta({
      concept_questions_active: false,
      micro_quiz_hold: 0,
      concept_teaching_await_vtse_done: 1,
      flow_checkpoint_pending: false,
    });
    const protectedMeta = protectConceptCheckMeta(prev, incoming, {
      type: "noop",
    });
    assert.ok(protectedMeta);
    assert.equal(protectedMeta!.concept_questions_active, true);
    assert.equal(protectedMeta!.micro_interaction_prompt, "Name one chamber.");
  });
});

describe("deriveSessionUi concept_question", () => {
  it("arms panel state without requiring prior meta prompt", () => {
    const ui = deriveSessionUi({
      type: "concept_question",
      message: "Which vessel returns blood?",
      question: "Which vessel returns blood?",
      current_concept: "Circulation",
      flow_state: "concept_questions",
    });
    assert.equal(ui.flowState, "concept_questions");
    assert.equal(ui.sessionMeta?.concept_questions_active, true);
    assert.equal(ui.sessionMeta?.micro_quiz_hold, 1);
    assert.equal(
      ui.sessionMeta?.micro_interaction_prompt,
      "Which vessel returns blood?",
    );
    assert.equal(shouldShowConceptCheckQuestion(ui.sessionMeta), true);
  });

  it("does not lose stem when continue_ack merges afterward", () => {
    let ui = deriveSessionUi({
      type: "concept_question",
      message: "What is the aorta?",
      question: "What is the aorta?",
    });
    ui = deriveSessionUi(
      {
        type: "flow_checkpoint_continue_ack",
        outcome: "already_cleared",
        flow_checkpoint_pending: 0,
        meta: baseMeta({
          concept_questions_active: true,
          micro_quiz_hold: 0,
          concept_teaching_await_vtse_done: 1,
        }),
      },
      ui,
    );
    assert.equal(
      ui.sessionMeta?.micro_interaction_prompt,
      "What is the aorta?",
    );
    assert.equal(shouldShowConceptCheckQuestion(ui.sessionMeta), true);
  });
});
