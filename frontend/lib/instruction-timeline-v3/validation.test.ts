import test from "node:test";
import assert from "node:assert/strict";

import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import { validateTimeline } from "@/lib/instruction-timeline-v3/validation";

function minimalBeat(
  beatId: string,
  index: number,
  operations: InstructionTimelineV3["beats"][0]["operations"],
): InstructionTimelineV3["beats"][0] {
  return {
    beat_id: beatId,
    index,
    pacing_mode: "deliver",
    pedagogy: { zone: 1, goal: "test", interaction_expected: false },
    sync: {
      completion_policy: "all_ops_done",
      allow_parallel_ops: false,
      barrier_after_beat: true,
    },
    operations,
    narration_segments: [],
    bindings: [],
    interaction_gate: {
      type: "none",
      required: false,
      resume_policy: "continue_same_timeline",
    },
  };
}

function minimalTimeline(beats: InstructionTimelineV3["beats"]): InstructionTimelineV3 {
  return {
    schema_version: "3.0.0",
    timeline_id: "tlm_crossbeattest",
    session_id: "sess_x",
    timeline_kind: "opening_arc",
    created_at: new Date().toISOString(),
    planner: {
      planner_version: "test",
      planner_config_hash: "sha256:pcfg",
    },
    determinism: {
      layout_seed: 1,
      initial_scene_hash: "sha256:init",
      expected_final_scene_hash: "sha256:end",
    },
    global_sync_policy: {
      clock_mode: "timer_only",
      fallback_clock_mode: "timer_only",
      min_delay_ms: 350,
      max_silence_before_fallback_ms: 1500,
    },
    scene_bootstrap: { entities: {}, root_order: [] },
    layout_metadata: {
      layout_profile: "flow_horizontal",
      viewport: { min_width: 960, min_height: 540 },
      constraints_hash: "sha256:lay",
    },
    replay_metadata: {
      snapshot_interval_ops: 20,
      record_event_log: true,
      hash_algorithm: "sha256",
      replay_mode_default: "exact_timing",
    },
    beats,
  };
}

test("cross-beat depends_on is valid (global DAG)", () => {
  const op0: InstructionTimelineV3["beats"][0]["operations"][0] = {
    operation_id: "op_000001",
    op_type: "add_entity",
    beat_id: "beat_0000",
    depends_on: [],
    payload: {
      entity: {
        entity_id: "node_a",
        entity_type: "Node",
        kind: "primitive",
        version: 1,
        label: "A",
        spatial: { x: 0, y: 0, w: 100, h: 50 },
        semantic: { role: "concept" },
        render: { layer: 1 },
        lifecycle: { state: "active", created_by_op: "op_000001" },
      },
    },
    sync: { execution_mode: "instant_commit", binding_mode: "independent" },
    reversibility: { reversible: true, inverse_op_type: null },
    preconditions: [],
    postconditions: [],
    determinism_key: "sha256:a",
  };
  const op1: InstructionTimelineV3["beats"][0]["operations"][0] = {
    operation_id: "op_000002",
    op_type: "add_entity",
    beat_id: "beat_0001",
    depends_on: ["op_000001"],
    payload: {
      entity: {
        entity_id: "node_b",
        entity_type: "Node",
        kind: "primitive",
        version: 1,
        label: "B",
        spatial: { x: 100, y: 0, w: 100, h: 50 },
        semantic: { role: "concept" },
        render: { layer: 1 },
        lifecycle: { state: "active", created_by_op: "op_000002" },
      },
    },
    sync: { execution_mode: "instant_commit", binding_mode: "independent" },
    reversibility: { reversible: true, inverse_op_type: null },
    preconditions: [],
    postconditions: [],
    determinism_key: "sha256:b",
  };

  const t = minimalTimeline([
    minimalBeat("beat_0000", 0, [op0]),
    minimalBeat("beat_0001", 1, [op1]),
  ]);

  const result = validateTimeline(t);
  assert.equal(result.ok, true, JSON.stringify(result.errors, null, 2));
});

test("empty string topic_id is normalized and accepted", () => {
  const t = minimalTimeline([
    minimalBeat("beat_0000", 0, [
      {
        operation_id: "op_000001",
        op_type: "add_entity",
        beat_id: "beat_0000",
        depends_on: [],
        payload: {
          entity: {
            entity_id: "node_a",
            entity_type: "Node",
            kind: "primitive",
            version: 1,
            label: "A",
            spatial: { x: 0, y: 0, w: 100, h: 50 },
            semantic: { role: "concept" },
            render: { layer: 1 },
            lifecycle: { state: "active", created_by_op: "op_000001" },
          },
        },
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        reversibility: { reversible: true, inverse_op_type: null },
        preconditions: [],
        postconditions: [],
        determinism_key: "sha256:a",
      },
    ]),
  ]);
  (t as { topic_id?: string }).topic_id = "";

  const result = validateTimeline(t);
  assert.equal(result.ok, true, JSON.stringify(result.errors, null, 2));
});

test("attempt nonce stays inside tlm_ plus alphanumerics", () => {
  const beat = minimalBeat("beat_0000", 0, [
    {
      operation_id: "op_000001",
      op_type: "add_entity",
      beat_id: "beat_0000",
      depends_on: [],
      payload: {
        entity: {
          entity_id: "node_a",
          entity_type: "Node",
          kind: "primitive",
          version: 1,
          label: "A",
          spatial: { x: 0, y: 0, w: 100, h: 50 },
          semantic: { role: "concept" },
          render: { layer: 1 },
          lifecycle: { state: "active", created_by_op: "op_000001" },
        },
      },
      sync: { execution_mode: "instant_commit", binding_mode: "independent" },
      reversibility: { reversible: true, inverse_op_type: null },
      preconditions: [],
      postconditions: [],
      determinism_key: "sha256:a",
    },
  ]);
  const broken = minimalTimeline([beat]);
  broken.timeline_id = "tlm_9ba5143c9f89_64c99c6b";
  const rejected = validateTimeline(broken);
  assert.equal(rejected.ok, false);
  assert.equal(rejected.errors?.[0]?.path, "timeline_id");

  const profiles = [
    "hierarchy_root_children",
    "grouped_clusters",
    "comparison_split",
    "cycle_ring",
    "vertical_process_phaseA",
  ] as const;
  for (const profile of profiles) {
    const okTimeline = minimalTimeline([beat]);
    okTimeline.timeline_id = "tlm_9ba5143c9f8964c99c6b";
    okTimeline.layout_metadata = {
      ...okTimeline.layout_metadata,
      layout_profile: profile,
    };
    const accepted = validateTimeline(okTimeline);
    assert.equal(
      accepted.ok,
      true,
      `${profile} ${JSON.stringify(accepted.errors)}`,
    );
  }
});
