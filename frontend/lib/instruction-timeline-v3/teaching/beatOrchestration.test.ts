import { describe, expect, it } from "vitest";
import type { Beat } from "@/lib/instruction-timeline-v3/types";
import {
  beatUsesOrchestration,
  buildBeatOrchestrationPlan,
} from "@/lib/instruction-timeline-v3/teaching/beatOrchestration";

function legacyBeat(): Beat {
  return {
    beat_id: "beat_0000",
    index: 0,
    pacing_mode: "deliver",
    pedagogy: {
      zone: 1,
      goal: "g",
      interaction_expected: false,
    },
    sync: {
      completion_policy: "all_ops_and_narration_done",
      allow_parallel_ops: false,
      barrier_after_beat: true,
    },
    operations: [
      {
        operation_id: "op_1",
        beat_id: "beat_0000",
        op_type: "add_entity",
        depends_on: [],
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        payload: {
          entity: {
            entity_id: "node_1",
            entity_type: "Node",
            kind: "primitive",
            version: 1,
            spatial: { x: 0, y: 0, w: 1, h: 1 },
            semantic: { role: "concept_step" },
            render: { layer: 0, visible: true },
            lifecycle: { state: "active", created_by_op: "op_1" },
            label: "A",
          },
        },
      },
    ],
    narration_segments: [
      {
        segment_id: "seg_beat_0000",
        beat_id: "beat_0000",
        text: "One line.",
        speech: { required: true, interruptible: false },
        timing: { mode: "timer_only", min_visible_ms: 300 },
        anchor: "during_ops",
      },
    ],
    bindings: [
      {
        binding_id: "bind_0",
        segment_id: "seg_beat_0000",
        operation_id: "op_1",
        relation: "on_segment_start",
      },
    ],
    interaction_gate: {
      type: "none",
      required: false,
      resume_policy: "continue_same_timeline",
    },
  };
}

function orchestratedBeat(): Beat {
  const base = legacyBeat();
  return {
    ...base,
    metadata: { orchestration_v1: true },
    operations: [
      ...base.operations,
      {
        operation_id: "op_2",
        beat_id: "beat_0000",
        op_type: "annotate_entity",
        depends_on: ["op_1"],
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        payload: {
          annotation_id: "ann_1",
          target_id: "node_1",
          text: "note",
          entity: {
            entity_id: "ann_1",
            entity_type: "Annotation",
            kind: "primitive",
            version: 1,
            spatial: { x: 0, y: 0, w: 1, h: 1 },
            semantic: { role: "annotation" },
            render: { layer: 0, visible: true },
            lifecycle: { state: "active", created_by_op: "op_2" },
            label: "",
            text: "note",
            target_id: "node_1",
          },
        },
      },
      {
        operation_id: "op_3",
        beat_id: "beat_0000",
        op_type: "connect_entities",
        depends_on: ["op_2"],
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        payload: {
          edge_id: "edge_1",
          from_id: "node_0",
          to_id: "node_1",
          entity: {
            entity_id: "edge_1",
            entity_type: "Edge",
            kind: "primitive",
            version: 1,
            spatial: { x: 0, y: 0, w: 1, h: 1 },
            semantic: { role: "edge" },
            render: { layer: 0, visible: true },
            lifecycle: { state: "active", created_by_op: "op_3" },
            label: "",
            from_id: "node_0",
            to_id: "node_1",
          },
        },
      },
      {
        operation_id: "op_4",
        beat_id: "beat_0000",
        op_type: "highlight_entity",
        depends_on: ["op_3"],
        sync: { execution_mode: "instant_commit", binding_mode: "independent" },
        payload: {
          highlight_id: "hl_1",
          target_ids: ["node_1"],
          entity: {
            entity_id: "hl_1",
            entity_type: "Highlight",
            kind: "primitive",
            version: 1,
            spatial: { x: 0, y: 0, w: 1, h: 1 },
            semantic: { role: "highlight" },
            render: { layer: 0, visible: true },
            lifecycle: { state: "active", created_by_op: "op_4" },
            label: "",
            target_ids: ["node_1"],
          },
        },
      },
    ],
    narration_segments: [
      {
        ...base.narration_segments[0]!,
        metadata: {
          orchestration_v1: true,
          pause_after_ms: 300,
          reveal_offset_ms: 400,
        },
      },
    ],
    bindings: [
      { binding_id: "b0", segment_id: "seg_beat_0000", operation_id: "op_1", relation: "on_segment_start" },
      { binding_id: "b1", segment_id: "seg_beat_0000", operation_id: "op_2", relation: "during_segment" },
      { binding_id: "b2", segment_id: "seg_beat_0000", operation_id: "op_3", relation: "on_segment_end" },
      { binding_id: "b3", segment_id: "seg_beat_0000", operation_id: "op_4", relation: "after_segment" },
    ],
  };
}

describe("beatOrchestration", () => {
  it("detects legacy single-binding beats", () => {
    expect(beatUsesOrchestration(legacyBeat())).toBe(false);
    const plan = buildBeatOrchestrationPlan(legacyBeat(), 350);
    expect(plan?.orchestrated).toBe(false);
  });

  it("builds choreographed plan for multi-binding beats", () => {
    const beat = orchestratedBeat();
    expect(beatUsesOrchestration(beat)).toBe(true);
    const plan = buildBeatOrchestrationPlan(beat, 350);
    expect(plan?.orchestrated).toBe(true);
    expect(plan?.onStart).toEqual(["op_1"]);
    expect(plan?.during[0]?.operationId).toBe("op_2");
    expect(plan?.during[0]?.revealOffsetMs).toBe(400);
    expect(plan?.onEnd).toEqual(["op_3"]);
    expect(plan?.after).toEqual(["op_4"]);
    expect(plan?.pauseAfterMs).toBe(300);
  });

});
