import assert from "node:assert/strict";
import test from "node:test";

import { deriveInstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  processAnnotationVisible,
  resolveProcessStepPhase,
} from "@/lib/instruction-timeline-v3/teaching/flowProcessPresentation";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

function timelineWithProfile(profile: string, extra: Record<string, unknown> = {}): InstructionTimelineV3 {
  return {
    schema_version: "3.0.0",
    timeline_id: "tl_test",
    session_id: "sess",
    topic_id: "topic",
    concept_id: "concept",
    timeline_kind: "opening_arc",
    created_at: "2026-01-01T00:00:00Z",
    planner: {
      planner_version: "test",
      planner_config_hash: "sha256:test",
    },
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
    beats: [],
    layout_metadata: {
      layout_profile: profile as InstructionTimelineV3["layout_metadata"]["layout_profile"],
      viewport: { min_width: 960, min_height: 540 },
      constraints_hash: "sha256:c",
      ...extra,
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

test("deriveInstructionalLayoutKind maps vertical_process_phaseA to flow_vertical_process", () => {
  assert.equal(
    deriveInstructionalLayoutKind(timelineWithProfile("vertical_process_phaseA")),
    "flow_vertical_process",
  );
});

test("process staged reveal emphasizes focus step only", () => {
  const ids = ["node_1", "node_2", "node_3"];
  assert.equal(resolveProcessStepPhase("node_1", null, ids), "focus");
  assert.equal(resolveProcessStepPhase("node_2", null, ids), "neutral");
  assert.equal(resolveProcessStepPhase("node_2", "node_2", ids), "focus");
  assert.equal(resolveProcessStepPhase("node_1", "node_2", ids), "completed");
  assert.equal(processAnnotationVisible("completed", true), true);
  assert.equal(processAnnotationVisible("focus", true), true);
  assert.equal(processAnnotationVisible("neutral", true), false);
});
