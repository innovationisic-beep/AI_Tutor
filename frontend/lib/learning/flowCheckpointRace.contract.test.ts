import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { isFlowCheckpointContinueAck } from "@/lib/learning/flowCheckpointContinue";
import {
  buildFlowCheckpointEventForBeat,
  isFlowCheckpointBlockingVtseStageDone,
  isFlowCheckpointEligible,
  processFlowCheckpointKind,
  shouldTriggerFlowCheckpoint,
} from "@/lib/learning/flowCheckpointOrchestrator";
import { isConceptVtseStageDoneAccepted } from "@/lib/learning/vtseStageDoneGuard";
import type { Beat, InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

const root = join(__dirname, "../..");

function flowTimeline(nodeLabels: string[]): InstructionTimelineV3 {
  const beats: Beat[] = nodeLabels.map((label, i) => ({
    beat_id: `beat_${i}`,
    index: i,
    pacing_mode: "guided",
    pedagogy: {
      zone: 1,
      goal: "explain",
      interaction_expected: false,
    },
    sync: {
      completion_policy: "all_ops_and_narration_done",
      allow_parallel_ops: false,
      barrier_after_beat: true,
    },
    operations: [
      {
        op_id: `op_${i}`,
        op_type: "add_entity",
        payload: {
          entity: {
            entity_id: `node_${i}`,
            entity_type: "Node",
            label,
            semantic: { role: "process_step" },
          },
        },
      },
    ],
    narration_segments: [],
    bindings: [],
    interaction_gate: {
      gate_kind: "none",
      required: false,
      resume_policy: "continue_same_timeline",
    },
  }));

  return {
    schema_version: "3.0.0",
    timeline_id: "tl_flow_cp_race",
    session_id: "sess",
    topic_id: "topic",
    concept_id: "concept",
    timeline_kind: "opening_arc",
    created_at: "2026-01-01T00:00:00Z",
    planner: { planner_version: "test", planner_config_hash: "sha256:test" },
    determinism: {
      layout_seed: 1,
      initial_scene_hash: "sha256:a",
      expected_final_scene_hash: "sha256:b",
    },
    global_sync_policy: {
      clock_mode: "timer_only",
      fallback_clock_mode: "timer_only",
      min_delay_ms: 350,
      max_silence_before_fallback_ms: 1500,
    },
    scene_bootstrap: { entities: {}, root_order: [] },
    beats,
    layout_metadata: {
      layout_profile: "vertical_process_phaseA",
      viewport: { min_width: 960, min_height: 540 },
      constraints_hash: "sha256:c",
    },
    replay_metadata: {
      snapshot_interval_ops: 20,
      record_event_log: true,
      hash_algorithm: "sha256",
      replay_mode_default: "exact_timing",
    },
    compatibility: { source_pipeline: "native_v3" },
  };
}

describe("flowCheckpointContinue ack helper", () => {
  it("accepts accepted and already_cleared", () => {
    assert.equal(
      isFlowCheckpointContinueAck({
        type: "flow_checkpoint_continue_ack",
        outcome: "accepted",
        flow_checkpoint_pending: 0,
      }),
      true,
    );
    assert.equal(
      isFlowCheckpointContinueAck({
        type: "flow_checkpoint_continue_ack",
        outcome: "already_cleared",
        flow_checkpoint_pending: 0,
      }),
      true,
    );
  });

  it("rejects noop and clarification", () => {
    assert.equal(isFlowCheckpointContinueAck({ type: "noop" }), false);
    assert.equal(
      isFlowCheckpointContinueAck({
        type: "flow_checkpoint_clarification",
        message: "x",
      }),
      false,
    );
  });
});

describe("vtseStageDoneGuard", () => {
  it("rejects noop while still awaiting (checkpoint race)", () => {
    assert.equal(
      isConceptVtseStageDoneAccepted(
        { type: "noop" },
        { concept_teaching_await_vtse_done: 1 } as never,
      ),
      false,
    );
  });

  it("accepts noop when await cleared (idempotent already completed)", () => {
    assert.equal(
      isConceptVtseStageDoneAccepted(
        { type: "noop" },
        {
          concept_teaching_await_vtse_done: 0,
          concept_questions_active: true,
        } as never,
      ),
      true,
    );
  });

  it("accepts concept_question arm", () => {
    assert.equal(
      isConceptVtseStageDoneAccepted({
        type: "concept_question",
        message: "Check?",
        current_concept: "X",
      }),
      true,
    );
  });

  it("rejects checkpoint continue ack as stage completion", () => {
    assert.equal(
      isConceptVtseStageDoneAccepted({
        type: "flow_checkpoint_continue_ack",
        outcome: "accepted",
      }),
      false,
    );
  });
});

describe("linear_process final-checkpoint matrix", () => {
  for (const n of [2, 4, 6, 8] as const) {
    it(`${n} nodes: checkpoints every 2; Concept Check only after final`, () => {
      const labels = Array.from({ length: n }, (_, i) => `Step ${i + 1}`);
      const tl = flowTimeline(labels);
      assert.equal(isFlowCheckpointEligible(tl), true);

      const kinds: Array<"none" | "intermediate" | "final"> = [];
      for (let i = 0; i < n; i++) {
        const beat = tl.beats[i]!;
        const ev = buildFlowCheckpointEventForBeat(tl, beat);
        const kind = processFlowCheckpointKind(i + 1, n);
        kinds.push(kind);
        if (kind === "none") {
          assert.equal(ev, null);
        } else {
          assert.ok(ev, `expected checkpoint at node ${i + 1}`);
          assert.equal(ev.completedNodeCount, i + 1);
        }
      }

      const intermediate = kinds.filter((k) => k === "intermediate");
      const finals = kinds.filter((k) => k === "final");
      assert.equal(finals.length, 1, "exactly one final checkpoint opportunity");
      assert.equal(kinds[n - 1], "final");
      // Intermediate checkpoints exist for 4+ nodes; must not imply stage_done.
      if (n > 2) {
        assert.ok(intermediate.length >= 1);
        assert.ok(
          intermediate.every((k) => k === "intermediate"),
        );
      }
      assert.equal(shouldTriggerFlowCheckpoint(n), true);
    });
  }

  for (const n of [3, 5, 7] as const) {
    it(`${n} nodes: final node is non-checkpoint; earlier even counts still gate`, () => {
      const labels = Array.from({ length: n }, (_, i) => `Step ${i + 1}`);
      const tl = flowTimeline(labels);
      const last = tl.beats[n - 1]!;
      assert.equal(buildFlowCheckpointEventForBeat(tl, last), null);
      assert.equal(processFlowCheckpointKind(n, n), "none");
      assert.equal(shouldTriggerFlowCheckpoint(n), false);
      assert.equal(shouldTriggerFlowCheckpoint(2), true);
      const mid = tl.beats[1]!;
      assert.ok(buildFlowCheckpointEventForBeat(tl, mid));
      assert.equal(processFlowCheckpointKind(2, n), "intermediate");
    });
  }

  it("checkpoint UI blocks stage_done until idle (continue + question branches)", () => {
    assert.equal(
      isFlowCheckpointBlockingVtseStageDone({ isActive: true, continuing: false }),
      true,
    );
    assert.equal(
      isFlowCheckpointBlockingVtseStageDone({ isActive: false, continuing: true }),
      true,
    );
    assert.equal(
      isFlowCheckpointBlockingVtseStageDone({ isActive: false, continuing: false }),
      false,
    );
  });
});

describe("production VTSE template checkpoint isolation", () => {
  it("FlowCheckpoint remains linear_process / flow_vertical_process only", () => {
    const orch = readFileSync(
      join(root, "lib/learning/flowCheckpointOrchestrator.ts"),
      "utf8",
    );
    assert.match(orch, /flow_vertical_process/);
    assert.match(
      orch,
      /isFlowCheckpointEligible[\s\S]*flow_vertical_process/,
    );
  });

  it("non-process layout profiles never emit FlowCheckpoint events", () => {
    const nonProcessProfiles = [
      "hierarchy_root_children",
      "grouped_clusters",
      "comparison_columns",
      "cycle_ring",
    ] as const;
    for (const profile of nonProcessProfiles) {
      const tl = flowTimeline(["A", "B"]);
      tl.layout_metadata = {
        ...tl.layout_metadata,
        layout_profile: profile,
      };
      assert.equal(
        isFlowCheckpointEligible(tl),
        false,
        `expected no checkpoint for ${profile}`,
      );
      assert.equal(buildFlowCheckpointEventForBeat(tl, tl.beats[1]!), null);
    }
  });

  it("controller awaits continue ack before resumeTimeline", () => {
    const src = readFileSync(
      join(root, "lib/learning/useFlowCheckpointController.ts"),
      "utf8",
    );
    assert.match(src, /isFlowCheckpointContinueAck/);
    assert.match(src, /await sendMessage/);
    assert.match(src, /resumeTimeline\(reason\)/);
    assert.doesNotMatch(
      src,
      /void sendMessage\(sessionId,\s*"__action:flow_checkpoint_continue"/,
    );
    assert.doesNotMatch(src, /setTimeout/);
  });

  it("learn page confirms stage_done only after acceptance", () => {
    const page = readFileSync(
      join(root, "app/(app)/learn/[topicId]/page.tsx"),
      "utf8",
    );
    assert.match(page, /isConceptVtseStageDoneAccepted/);
    assert.match(page, /vtseStageDoneGuardRef/);
    assert.match(page, /shouldShowConceptCheckQuestion/);
    assert.match(
      page,
      /quizTriggeredForRef\.current = completedId[\s\S]*confirmed: true/,
    );
    assert.match(
      page,
      /flowCheckpoint\.ui\.isActive \|\| flowCheckpoint\.ui\.continuing/,
    );
  });

  it("timeline released outcome does not call onInstructionComplete", () => {
    const src = readFileSync(
      join(root, "components/ai/timeline-v3/ProductionTimelineRuntimeView.tsx"),
      "utf8",
    );
    assert.match(src, /outcome === "released"/);
    assert.match(
      src,
      /outcome === "released"[\s\S]*?else \{\s*onInstructionCompleteRef/,
    );
    // released branch must not invoke the complete callback.
    const releasedBlock = src.slice(
      src.indexOf('outcome === "released"'),
      src.indexOf("onInstructionCompleteRef.current?.()"),
    );
    assert.doesNotMatch(releasedBlock, /onInstructionCompleteRef\.current\?\.\(\)/);
  });

  it("concept_question is panel-owned (not board bubble)", () => {
    const chat = readFileSync(join(root, "hooks/useChat.ts"), "utf8");
    assert.match(
      chat,
      /if\s*\(res\.type\s*===\s*"concept_question"\)\s*return\s*\[\]/,
    );
    const api = readFileSync(join(root, "lib/api.ts"), "utf8");
    assert.match(api, /t === "concept_question"/);
  });

  it("overlay exposes retryable continuing / error state", () => {
    const overlay = readFileSync(
      join(root, "components/learning/FlowCheckpointOverlay.tsx"),
      "utf8",
    );
    assert.match(overlay, /continuing/);
    assert.match(overlay, /continueError/);
    assert.match(overlay, /flow-checkpoint-continue-error/);
  });
});
