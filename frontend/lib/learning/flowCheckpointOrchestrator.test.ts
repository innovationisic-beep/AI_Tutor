import assert from "node:assert/strict";
import test from "node:test";

import {
  buildFlowCheckpointEventForBeat,
  isFlowCheckpointBlockingVtseStageDone,
  orderedFlowProcessNodes,
  processFlowCheckpointKind,
  shouldTriggerFlowCheckpoint,
} from "@/lib/learning/flowCheckpointOrchestrator";
import type { Beat, InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

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
    timeline_id: "tl_flow_cp",
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

test("orderedFlowProcessNodes preserves beat order and labels", () => {
  const tl = flowTimeline(["Mouth", "Esophagus", "Stomach"]);
  const nodes = orderedFlowProcessNodes(tl);
  assert.equal(nodes.length, 3);
  assert.deepEqual(nodes.map((n) => n.label), ["Mouth", "Esophagus", "Stomach"]);
});

test("shouldTriggerFlowCheckpoint every 2 completed nodes", () => {
  assert.equal(shouldTriggerFlowCheckpoint(1), false);
  assert.equal(shouldTriggerFlowCheckpoint(2), true);
  assert.equal(shouldTriggerFlowCheckpoint(3), false);
  assert.equal(shouldTriggerFlowCheckpoint(4), true);
});

test("processFlowCheckpointKind distinguishes intermediate vs final", () => {
  assert.equal(processFlowCheckpointKind(2, 6), "intermediate");
  assert.equal(processFlowCheckpointKind(4, 6), "intermediate");
  assert.equal(processFlowCheckpointKind(6, 6), "final");
  assert.equal(processFlowCheckpointKind(2, 2), "final");
  assert.equal(processFlowCheckpointKind(3, 5), "none");
  assert.equal(processFlowCheckpointKind(2, 5), "intermediate");
});

test("isFlowCheckpointBlockingVtseStageDone covers continue branch", () => {
  assert.equal(
    isFlowCheckpointBlockingVtseStageDone({ isActive: true }),
    true,
  );
  assert.equal(
    isFlowCheckpointBlockingVtseStageDone({ isActive: false, continuing: true }),
    true,
  );
  assert.equal(
    isFlowCheckpointBlockingVtseStageDone({ isActive: false }),
    false,
  );
});

test("buildFlowCheckpointEventForBeat uses completed flow nodes not beat count alone", () => {
  const tl = flowTimeline(["Mouth", "Esophagus", "Stomach", "Small Intestine"]);
  const beat1 = tl.beats[1]!;
  const ev = buildFlowCheckpointEventForBeat(tl, beat1);
  assert.ok(ev);
  assert.deepEqual(ev.stepLabels, ["Mouth", "Esophagus"]);
  assert.equal(ev.completedNodeCount, 2);
  assert.equal(ev.checkpointIndex, 0);

  const beat3 = tl.beats[3]!;
  const ev2 = buildFlowCheckpointEventForBeat(tl, beat3);
  assert.ok(ev2);
  assert.deepEqual(ev2.stepLabels, ["Stomach", "Small Intestine"]);
  assert.equal(ev2.completedNodeCount, 4);
});
