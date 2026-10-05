import test from "node:test";
import assert from "node:assert/strict";

import { deriveInstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  applyInstructionalLayout,
  cycleRingRadius,
  CYCLE_RING_CY_RATIO,
} from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

const WIDTH = 960;
const HEIGHT = 1040;

function mockNode(id: string): RenderNodeProjection {
  return {
    projection_id: `proj_${id}`,
    source_entity_id: id,
    projection_kind: "node",
    projection_version: "1.0.0",
    layer: "nodes",
    z_index: 10,
    visible: true,
    viewport_box: { x: 0, y: 0, w: 168, h: 72 },
    render_meta: {},
    projection_hash: "sha256:mock",
    label: id,
  };
}

function timelineWithProfile(layout_profile: InstructionTimelineV3["layout_metadata"]["layout_profile"]): InstructionTimelineV3 {
  return {
    schema_version: "3.0.0",
    timeline_id: "tlm_test",
    session_id: "sess",
    timeline_kind: "opening_arc",
    created_at: "2026-01-01T00:00:00Z",
    planner: { planner_version: "v1", planner_config_hash: "sha256:p" },
    determinism: {
      layout_seed: 1,
      initial_scene_hash: "sha256:i",
      expected_final_scene_hash: "sha256:f",
    },
    global_sync_policy: {
      clock_mode: "timer_only",
      fallback_clock_mode: "timer_only",
      min_delay_ms: 350,
      max_silence_before_fallback_ms: 1500,
    },
    scene_bootstrap: { entities: {}, root_order: [] },
    layout_metadata: {
      layout_profile,
      viewport: { min_width: WIDTH, min_height: HEIGHT },
      constraints_hash: "sha256:l",
    },
    replay_metadata: {
      snapshot_interval_ops: 20,
      record_event_log: true,
      hash_algorithm: "sha256",
      replay_mode_default: "exact_timing",
    },
    beats: [],
  };
}

test("deriveInstructionalLayoutKind maps cycle_radial and cycle_ring to cycle_ring", () => {
  assert.equal(deriveInstructionalLayoutKind(timelineWithProfile("cycle_radial")), "cycle_ring");
  assert.equal(deriveInstructionalLayoutKind(timelineWithProfile("cycle_ring")), "cycle_ring");
});

test("deriveInstructionalLayoutKind keeps hierarchy unchanged", () => {
  assert.equal(
    deriveInstructionalLayoutKind(timelineWithProfile("hierarchy_root_children")),
    "hierarchy_root_children",
  );
});

test("cycle_ring places 3, 5, and 8 nodes on a ring with distinct angles", () => {
  const cx = WIDTH / 2;
  const cy = HEIGHT * CYCLE_RING_CY_RATIO;

  for (const n of [3, 5, 8]) {
    const nodes = Array.from({ length: n }, (_, i) => mockNode(`node_${i + 1}`));
    const laidOut = applyInstructionalLayout(nodes, WIDTH, HEIGHT, "cycle_ring");
    const centers = laidOut.map((p) => ({
      x: p.viewport_box.x + p.viewport_box.w / 2,
      y: p.viewport_box.y + p.viewport_box.h / 2,
    }));
    assert.equal(centers.length, n);

    const radii = centers.map((c) => Math.hypot(c.x - cx, c.y - cy));
    const rExpected = cycleRingRadius(n, WIDTH, HEIGHT);
    for (const r of radii) {
      assert.ok(Math.abs(r - rExpected) < 48, `radius ${r} vs expected ${rExpected}`);
    }

    const angles = centers.map((c) => Math.atan2(c.y - cy, c.x - cx));
    const uniqueAngles = new Set(angles.map((a) => a.toFixed(3)));
    assert.equal(uniqueAngles.size, n, `expected ${n} distinct angles`);
  }
});
