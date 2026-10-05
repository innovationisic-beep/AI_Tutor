import test from "node:test";
import assert from "node:assert/strict";

import { normalizeTutorResponse } from "@/lib/api";
import type { AskQuestionApiBody } from "@/lib/types";

test("normalizeTutorResponse preserves instruction_timeline_v3 on explanation", () => {
  const raw: AskQuestionApiBody = {
    answer: "x",
    type: "explanation",
    message: "Timeline response",
    instruction_timeline_v3: {
      schema_version: "3.0.0",
      timeline_id: "tlm_TEST123",
      session_id: "sess_1",
      timeline_kind: "opening_arc",
      created_at: new Date().toISOString(),
      planner: { planner_version: "v1", planner_config_hash: "sha256:abc" },
      determinism: {
        layout_seed: 1,
        initial_scene_hash: "sha256:init",
        expected_final_scene_hash: "sha256:final",
      },
      global_sync_policy: {
        clock_mode: "timer_only",
        fallback_clock_mode: "timer_only",
        min_delay_ms: 0,
        max_silence_before_fallback_ms: 1000,
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
    timeline_metadata: { planner_source: "timeline_v3_native" },
    planner_source: "timeline_v3_native",
  };

  const normalized = normalizeTutorResponse(raw);
  assert.equal(normalized.type, "explanation");
  assert.ok(normalized.instruction_timeline_v3);
  assert.equal(normalized.planner_source, "timeline_v3_native");
});
