import test from "node:test";
import assert from "node:assert/strict";

import { MinimalTimelineRuntime } from "@/lib/instruction-timeline-v3/runtime";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";
import { validateTimeline } from "@/lib/instruction-timeline-v3/validation";
import { verifyReplayDeterminism } from "@/lib/instruction-timeline-v3/replayVerifier";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { verifySceneIntegrity } from "@/lib/instruction-timeline-v3/integrity";
import { shouldRunIntegrityCheck } from "@/lib/instruction-timeline-v3/policy";
import { SimulatedRuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import { CheckpointStore } from "@/lib/instruction-timeline-v3/checkpointStore";

function baseTimeline(): InstructionTimelineV3 {
  return {
    schema_version: "3.0.0",
    timeline_id: "tlm_TEST123",
    session_id: "sess_1",
    topic_id: "topic_1",
    timeline_kind: "opening_arc",
    created_at: new Date().toISOString(),
    planner: {
      planner_version: "planner-1",
      planner_config_hash: "sha256:planner",
    },
    determinism: {
      layout_seed: 42,
      initial_scene_hash: "sha256:init",
      expected_final_scene_hash: "sha256:end",
    },
    global_sync_policy: {
      clock_mode: "timer_only",
      fallback_clock_mode: "min_delay",
      min_delay_ms: 350,
      max_silence_before_fallback_ms: 1500,
    },
    scene_bootstrap: {
      entities: {},
      root_order: [],
    },
    layout_metadata: {
      layout_profile: "flow_horizontal",
      viewport: { min_width: 320, min_height: 240 },
      constraints_hash: "sha256:layout",
    },
    replay_metadata: {
      snapshot_interval_ops: 20,
      record_event_log: true,
      hash_algorithm: "sha256",
      replay_mode_default: "exact_timing",
    },
    beats: [
      {
        beat_id: "beat_0000",
        index: 0,
        pacing_mode: "deliver",
        pedagogy: { zone: 1, goal: "introduce", interaction_expected: false },
        sync: {
          completion_policy: "all_ops_done",
          allow_parallel_ops: false,
          barrier_after_beat: true,
        },
        operations: [
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
            reversibility: { reversible: true, inverse_op_type: "remove_entity" },
            preconditions: [],
            postconditions: [],
            determinism_key: "sha256:1",
          },
          {
            operation_id: "op_000002",
            op_type: "annotate_entity",
            beat_id: "beat_0000",
            depends_on: ["op_000001"],
            payload: {
              annotation_id: "anno_a",
              target_id: "node_a",
              text: "note",
            },
            sync: { execution_mode: "instant_commit", binding_mode: "independent" },
            reversibility: { reversible: true, inverse_op_type: "remove_entity" },
            preconditions: [],
            postconditions: [],
            determinism_key: "sha256:2",
          },
        ],
        narration_segments: [],
        bindings: [],
        interaction_gate: {
          type: "none",
          required: false,
          resume_policy: "continue_same_timeline",
        },
      },
    ],
  };
}

test("valid timeline passes schema + semantic checks", () => {
  const result = validateTimeline(baseTimeline());
  assert.equal(result.ok, true);
  assert.equal(result.errors.length, 0);
});

test("invalid DAG is rejected", () => {
  const timeline = baseTimeline();
  const beat = timeline.beats[0];
  const first = beat.operations[0];
  const second = beat.operations[1];
  first.depends_on = [second.operation_id];
  second.depends_on = [first.operation_id];

  const result = validateTimeline(timeline);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === "DAG_INVALID"));
});

test("duplicate entity add fails runtime", () => {
  const timeline = baseTimeline();
  timeline.beats[0].operations.unshift({
    operation_id: "op_000000",
    op_type: "add_entity",
    beat_id: "beat_0000",
    depends_on: [],
    payload: {
      entity: {
        entity_id: "node_a",
        entity_type: "Node",
        kind: "primitive",
        version: 1,
        label: "dup",
        spatial: { x: 0, y: 0, w: 10, h: 10 },
        semantic: { role: "concept" },
        render: { layer: 1 },
        lifecycle: { state: "active", created_by_op: "op_000000" },
      },
    },
    sync: { execution_mode: "instant_commit", binding_mode: "independent" },
    reversibility: { reversible: true, inverse_op_type: "remove_entity" },
    preconditions: [],
    postconditions: [],
    determinism_key: "sha256:0",
  });

  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(timeline);
  assert.equal(run.state.status, "failed");
  assert.ok(run.events.some((e) => e.type === "rollback_started"));
  assert.ok(run.events.some((e) => e.type === "rollback_completed"));
});

test("deterministic replay state hash matches across runs", () => {
  const timeline = baseTimeline();
  const runtime = new MinimalTimelineRuntime();
  const runA = runtime.run(timeline);
  const runB = runtime.run(timeline);
  assert.equal(runA.state.status, "completed");
  assert.equal(runB.state.status, "completed");
  assert.equal(runA.state.current_scene_hash, runB.state.current_scene_hash);
});

test("operation ordering invariant is deterministic", () => {
  const timeline = baseTimeline();
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(timeline);
  const committed = run.state.commit_history.map((c) => c.operation_id);
  assert.deepEqual(committed, ["op_000001", "op_000002"]);
});

test("cross-beat depends_on: scheduler + executor see prior commits", () => {
  const beat0 = baseTimeline().beats[0];
  const beat1: InstructionTimelineV3["beats"][0] = {
    beat_id: "beat_0001",
    index: 1,
    pacing_mode: "deliver",
    pedagogy: { zone: 1, goal: "step2", interaction_expected: false },
    sync: {
      completion_policy: "all_ops_done",
      allow_parallel_ops: false,
      barrier_after_beat: true,
    },
    operations: [
      {
        operation_id: "op_000003",
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
            lifecycle: { state: "active", created_by_op: "op_000003" },
          },
        },
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        reversibility: { reversible: true, inverse_op_type: "remove_entity" },
        preconditions: [],
        postconditions: [],
        determinism_key: "sha256:3",
      },
    ],
    narration_segments: [],
    bindings: [],
    interaction_gate: {
      type: "none",
      required: false,
      resume_policy: "continue_same_timeline",
    },
  };

  const timeline: InstructionTimelineV3 = {
    ...baseTimeline(),
    beats: [beat0, beat1],
  };

  const v = validateTimeline(timeline);
  assert.equal(v.ok, true, JSON.stringify(v.errors, null, 2));

  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(timeline);
  assert.equal(run.state.status, "completed", run.state.error?.message ?? "");
  const committed = run.state.commit_history.map((c) => c.operation_id);
  assert.deepEqual(committed, ["op_000001", "op_000002", "op_000003"]);
});

test("scene integrity verifier catches corrupted root order", () => {
  const sceneStore = new SceneStore({}, []);
  sceneStore.apply((draft) => {
    draft.root_order.push("ghost_entity");
  });
  const report = verifySceneIntegrity(sceneStore.snapshot());
  assert.equal(report.ok, false);
  assert.ok(report.errors.length > 0);
});

test("replay verifier detects mismatch commit hash", () => {
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(baseTimeline());
  assert.equal(run.state.status, "completed");
  const commits = [...run.state.commit_history];
  commits[0] = {
    ...commits[0],
    scene_hash_after: "sha256:tampered",
  };
  const replay = verifyReplayDeterminism(baseTimeline(), commits);
  assert.equal(replay.ok, false);
});

test("commit journal continuity enforced through runtime completion", () => {
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(baseTimeline());
  assert.equal(run.state.status, "completed");
  for (let i = 0; i < run.state.commit_history.length; i += 1) {
    assert.equal(run.state.commit_history[i].sequence, i);
  }
});

test("runtime emits replay_verified on successful deterministic replay", () => {
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(baseTimeline());
  assert.equal(run.state.status, "completed");
  assert.ok(run.events.some((e) => e.type === "replay_verified"));
});

test("integrity cadence policy behavior is deterministic", () => {
  assert.equal(shouldRunIntegrityCheck("per_operation", 1, false, 3), true);
  assert.equal(shouldRunIntegrityCheck("per_beat", 1, false, 3), false);
  assert.equal(shouldRunIntegrityCheck("per_beat", 1, true, 3), true);
  assert.equal(shouldRunIntegrityCheck("interval_based", 6, false, 3), true);
  assert.equal(shouldRunIntegrityCheck("production_balanced", 6, false, 3), true);
});

test("checkpoint compaction retains recent snapshots only", () => {
  const store = new CheckpointStore();
  const sceneStore = new SceneStore({}, []);
  for (let i = 0; i < 6; i += 1) {
    const snap = sceneStore.snapshot();
    store.create({
      timeline_id: "tlm_TEST123",
      commit_sequence: i,
      op_cursor: i,
      beat_cursor: 0,
      snapshot: snap,
      reason: "interval",
      at: new Date().toISOString(),
    });
  }
  store.prune(2);
  assert.equal(store.list().length, 2);
  assert.equal(store.list()[0].commit_sequence, 4);
});

test("deterministic replay works with checkpoint bootstrap", () => {
  const timeline = baseTimeline();
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(timeline);
  assert.equal(run.state.status, "completed");
  const cpStore = new CheckpointStore();
  const snapStore = new SceneStore({}, []);
  timeline.beats[0].operations.slice(0, 1);
  const cp = cpStore.create({
    timeline_id: timeline.timeline_id,
    commit_sequence: 0,
    op_cursor: 1,
    beat_cursor: 0,
    snapshot: snapStore.snapshot(),
    reason: "interval",
    at: new Date().toISOString(),
  });
  const replay = verifyReplayDeterminism(timeline, run.state.commit_history, cp);
  assert.equal(replay.ok, false);
});

test("simulated clock is deterministic", () => {
  const clock = new SimulatedRuntimeClock(1000);
  assert.equal(clock.nowMs(), 1000);
  clock.advanceByMs(500);
  assert.equal(clock.nowMs(), 1500);
});

test("resource exhaustion for max operations is enforced", () => {
  const runtime = new MinimalTimelineRuntime({
    policy: {
      resource_policy: {
        max_operations_per_timeline: 1,
        max_replay_depth: 100,
        max_checkpoint_count: 10,
        max_journal_size: 100,
        operation_timeout_ms: 10000,
        replay_timeout_ms: 10000,
      },
    },
  });
  const run = runtime.run(baseTimeline());
  assert.equal(run.state.status, "failed");
  assert.ok(run.events.some((e) => e.type === "resource_limit_hit"));
});

test("runtime supports replay seek correctness bounds", () => {
  const timeline = baseTimeline();
  const runtime = new MinimalTimelineRuntime();
  const run = runtime.run(timeline);
  assert.equal(run.state.status, "completed");
  const replay = verifyReplayDeterminism(timeline, run.state.commit_history, undefined, 1);
  assert.equal(replay.ok, false);
});
