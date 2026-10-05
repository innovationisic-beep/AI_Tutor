import test from "node:test";
import assert from "node:assert/strict";

import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";
import { SimulatedRuntimeClock } from "@/lib/instruction-timeline-v3/clock";
import { RuntimeRendererBridge } from "@/lib/instruction-timeline-v3/renderer/runtimeRendererBridge";
import { RenderScheduler } from "@/lib/instruction-timeline-v3/renderer/renderScheduler";
import { buildTransitionStateMap } from "@/lib/instruction-timeline-v3/renderer/transitionModel";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { MinimalTimelineRuntime } from "@/lib/instruction-timeline-v3/runtime";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

function miniTimeline(): InstructionTimelineV3 {
  return {
    schema_version: "3.0.0",
    timeline_id: "tlm_LIVE1",
    session_id: "sess",
    timeline_kind: "opening_arc",
    created_at: new Date().toISOString(),
    planner: { planner_version: "v1", planner_config_hash: "sha256:p" },
    determinism: {
      layout_seed: 1,
      initial_scene_hash: "sha256:i",
      expected_final_scene_hash: "sha256:f",
    },
    global_sync_policy: {
      clock_mode: "timer_only",
      fallback_clock_mode: "min_delay",
      min_delay_ms: 0,
      max_silence_before_fallback_ms: 1000,
    },
    scene_bootstrap: { entities: {}, root_order: [] },
    layout_metadata: {
      layout_profile: "flow_horizontal",
      viewport: { min_width: 320, min_height: 240 },
      constraints_hash: "sha256:l",
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
        pedagogy: { zone: 1, goal: "g", interaction_expected: false },
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
                entity_id: "n1",
                entity_type: "Node",
                kind: "primitive",
                version: 1,
                label: "N1",
                spatial: { x: 10, y: 10, w: 60, h: 30 },
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

test("projection stream ordering is monotonic", () => {
  const bus = new RuntimeEventBus();
  const bridge = new RuntimeRendererBridge({
    clock: new SimulatedRuntimeClock(0),
    eventBus: bus,
  });
  const store = new SceneStore({}, []);
  const snapshotA = store.snapshot();
  store.apply((draft) => {
    draft.entities_by_id.n1 = {
      entity_id: "n1",
      entity_type: "Node",
      kind: "primitive",
      version: 1,
      label: "A",
      spatial: { x: 0, y: 0, w: 10, h: 10 },
      semantic: { role: "concept" },
      render: { layer: 1 },
      lifecycle: { state: "active", created_by_op: "bootstrap" },
    };
  });
  const snapshotB = store.snapshot();
  const e1 = bridge.onCommittedOperation({ operation_id: "op_a", scene: snapshotA, at: new Date(0).toISOString() });
  const e2 = bridge.onCommittedOperation({ operation_id: "op_b", scene: snapshotB, at: new Date(1).toISOString() });
  assert.equal(e1.version, 0);
  assert.equal(e2.version, 1);
});

test("render scheduler flush ordering deterministic", () => {
  const scheduler = new RenderScheduler<{ id: string }>(new SimulatedRuntimeClock(0));
  scheduler.enqueue({ id: "b" });
  scheduler.enqueue({ id: "a" });
  const flushed = scheduler.flush(2);
  assert.deepEqual(
    flushed.map((f) => f.sequence),
    [0, 1],
  );
});

test("transition states classify diff entries correctly", () => {
  const map = buildTransitionStateMap(
    {
      added: [
        {
          projection_id: "p1",
          source_entity_id: "e1",
          projection_kind: "node",
          projection_version: "1.0.0",
          layer: "nodes",
          z_index: 1,
          visible: true,
          viewport_box: { x: 0, y: 0, w: 10, h: 10 },
          render_meta: {},
          projection_hash: "sha256:a",
          label: "a",
        },
      ],
      removed: [],
      updated: [],
      unchanged: [],
    },
    [],
  );
  assert.equal(map.p1.state, "entering");
});

test("runtime->bridge incremental construction consistency across runs", () => {
  const timeline = miniTimeline();
  const runBridge = () => {
    const clock = new SimulatedRuntimeClock(1000);
    const bus = new RuntimeEventBus();
    const bridge = new RuntimeRendererBridge({ clock, eventBus: bus });
    const runtime = new MinimalTimelineRuntime({ clock });
    runtime.run(timeline, {
      eventBus: bus,
      onOperationCommitted(payload) {
        bridge.onCommittedOperation({
          operation_id: payload.operation_id,
          scene: payload.scene,
          at: payload.at,
        });
      },
    });
    return bridge.getProjectionHistory().all().map((h) => h.snapshot.projection_hash);
  };
  const a = runBridge();
  const b = runBridge();
  assert.deepEqual(a, b);
});
