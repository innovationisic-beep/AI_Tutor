import test from "node:test";
import assert from "node:assert/strict";

import {
  resolveProductionVisualRenderer,
  type ProductionVisualBoardItem,
} from "@/lib/learning/productionVisualRenderer";

test("suppresses legacy svg when timeline schema is present", () => {
  const item: ProductionVisualBoardItem = {
    id: "item_1",
    instruction_timeline_v3: {
      schema_version: "3.0.0",
      timeline_id: "tlm_gate_test",
      session_id: "sess_1",
      timeline_kind: "opening_arc",
      created_at: "2026-05-20T12:00:00.000Z",
      planner: { planner_version: "v1", planner_config_hash: "sha256:abc" },
      determinism: {
        layout_seed: 1,
        initial_scene_hash: "sha256:init",
        expected_final_scene_hash: "sha256:final",
      },
      global_sync_policy: {
        clock_mode: "timer_only",
        fallback_clock_mode: "timer_only",
        min_delay_ms: 350,
        max_silence_before_fallback_ms: 1500,
      },
      scene_bootstrap: { entities: {}, root_order: [] },
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
          operations: [],
          narration_segments: [],
          bindings: [],
          interaction_gate: {
            type: "none",
            required: false,
            resume_policy: "continue_same_timeline",
          },
        },
      ],
      layout_metadata: {
        layout_profile: "flow_horizontal",
        viewport: { min_width: 960, min_height: 540 },
        constraints_hash: "sha256:layout",
      },
      replay_metadata: {
        snapshot_interval_ops: 20,
        record_event_log: true,
        hash_algorithm: "sha256",
        replay_mode_default: "exact_timing",
      },
    },
    visual: { svg: "<svg>legacy</svg>" },
  };

  const d = resolveProductionVisualRenderer(item, { useInstructionBoard: true });
  assert.equal(d.activeRenderer, "timeline_v3");
  assert.equal(d.suppressLegacySvg, true);
  assert.equal(d.suppressLegacyTeachingPayload, true);
});

test("falls back when beats array is empty", () => {
  const item: ProductionVisualBoardItem = {
    id: "item_2",
    instruction_timeline_v3: {
      schema_version: "3.0.0",
      timeline_id: "tlm_empty",
      session_id: "sess_1",
      timeline_kind: "opening_arc",
      created_at: "2026-05-20T12:00:00.000Z",
      planner: { planner_version: "v1", planner_config_hash: "sha256:abc" },
      determinism: {
        layout_seed: 1,
        initial_scene_hash: "sha256:init",
        expected_final_scene_hash: "sha256:final",
      },
      global_sync_policy: {
        clock_mode: "timer_only",
        fallback_clock_mode: "timer_only",
        min_delay_ms: 350,
        max_silence_before_fallback_ms: 1500,
      },
      scene_bootstrap: { entities: {}, root_order: [] },
      beats: [],
      layout_metadata: {
        layout_profile: "flow_horizontal",
        viewport: { min_width: 960, min_height: 540 },
        constraints_hash: "sha256:layout",
      },
      replay_metadata: {
        snapshot_interval_ops: 20,
        record_event_log: true,
        hash_algorithm: "sha256",
        replay_mode_default: "exact_timing",
      },
    },
    visual: { svg: "<svg/>" },
  };
  const d = resolveProductionVisualRenderer(item, { useInstructionBoard: true });
  assert.equal(d.activeRenderer, "legacy_prose");
  assert.equal(d.suppressLegacySvg, false);
});
