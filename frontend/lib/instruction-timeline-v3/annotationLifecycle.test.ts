import assert from "node:assert/strict";
import test from "node:test";

import {
  annotationPhase,
  buildAnnotationEntity,
  inferAnnotationKind,
  supersedeAnnotationsForNewOp,
  summarizeAnnotationLifecycle,
} from "@/lib/instruction-timeline-v3/annotationLifecycle";
import type { AnnotateEntityOp } from "@/lib/instruction-timeline-v3/types";
import { createDefaultOperationRegistry } from "@/lib/instruction-timeline-v3/operationRegistry";
import { OperationExecutor } from "@/lib/instruction-timeline-v3/executor";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { CommitJournal } from "@/lib/instruction-timeline-v3/commitJournal";

function annotateOp(id: string, opNum: number, beatId: string, targetId: string, text: string): AnnotateEntityOp {
  return {
    operation_id: `op_${String(opNum).padStart(6, "0")}`,
    op_type: "annotate_entity",
    beat_id: beatId,
    depends_on: [],
    payload: {
      annotation_id: id,
      target_id: targetId,
      text,
      style_token: "concept-annotation",
    },
    sync: { execution_mode: "instant_commit", binding_mode: "on_segment_start" },
    reversibility: { reversible: true, inverse_op_type: "remove_entity" },
    preconditions: [],
    postconditions: [],
    determinism_key: `sha256:${id}`,
  };
}

test("inferAnnotationKind detects incremental tutoring ids", () => {
  assert.equal(inferAnnotationKind("ann_1"), "pedagogical");
  assert.equal(inferAnnotationKind("ann_inc_3"), "incremental");
});

test("supersedeAnnotationsForNewOp compresses same-target active annotation", () => {
  const ann1 = buildAnnotationEntity(annotateOp("ann_1", 1, "b", "node_a", "first"));
  const entities: Record<string, import("@/lib/instruction-timeline-v3/types").SceneEntity> = {
    ann_1: ann1,
  };

  supersedeAnnotationsForNewOp(entities, "node_a", "op_000003");

  assert.equal(annotationPhase(entities.ann_1 as import("@/lib/instruction-timeline-v3/types").AnnotationEntity), "compressed");
});

test("active annotation on other target becomes passive when focus moves", () => {
  const annA = buildAnnotationEntity(annotateOp("ann_1", 1, "b", "node_a", "on A"));
  const annB = buildAnnotationEntity(annotateOp("ann_2", 2, "b", "node_b", "on B"));
  const entities: Record<string, import("@/lib/instruction-timeline-v3/types").SceneEntity> = {
    ann_1: annA,
    ann_2: annB,
  };

  supersedeAnnotationsForNewOp(entities, "node_b", "op_000004");

  assert.equal(annotationPhase(entities.ann_2 as import("@/lib/instruction-timeline-v3/types").AnnotationEntity), "compressed");
  assert.equal(annotationPhase(entities.ann_1 as import("@/lib/instruction-timeline-v3/types").AnnotationEntity), "passive");
});

test("incremental passive on same target becomes transient", () => {
  const inc = buildAnnotationEntity(annotateOp("ann_inc_1", 1, "b", "node_a", "probe note"));
  const entities: Record<string, import("@/lib/instruction-timeline-v3/types").SceneEntity> = {
    ann_inc_1: {
      ...inc,
      semantic: {
        role: "teacher_note",
        payload: { annotation_phase: "passive", annotation_kind: "incremental" },
      },
    },
  };

  supersedeAnnotationsForNewOp(entities, "node_a", "op_2");
  assert.equal(
    annotationPhase(entities.ann_inc_1 as import("@/lib/instruction-timeline-v3/types").AnnotationEntity),
    "transient",
  );
});

test("executor supersede chain on repeated annotate_entity", () => {
  const registry = createDefaultOperationRegistry();
  const executor = new OperationExecutor();
  const sceneStore = new SceneStore({}, []);
  const journal = new CommitJournal();
  const committedOps = new Set<string>();

  const nodeOp = {
    operation_id: "op_000001",
    op_type: "add_entity" as const,
    beat_id: "beat_0000",
    depends_on: [] as string[],
    payload: {
      entity: {
        entity_id: "node_a",
        entity_type: "Node" as const,
        kind: "primitive" as const,
        version: 1,
        label: "A",
        spatial: { x: 100, y: 100, w: 180, h: 90 },
        semantic: { role: "concept_step" },
        render: { layer: 2, style_token: "concept-node", visible: true },
        lifecycle: { state: "active" as const, created_by_op: "op_000001" },
      },
    },
    sync: { execution_mode: "instant_commit" as const, binding_mode: "on_segment_start" as const },
    reversibility: { reversible: true, inverse_op_type: "remove_entity" as const },
    preconditions: [],
    postconditions: [],
    determinism_key: "sha256:node" as const,
  };

  for (const op of [
    nodeOp,
    annotateOp("ann_1", 2, "beat_0000", "node_a", "Beat one note"),
    annotateOp("ann_2", 3, "beat_0001", "node_a", "Beat two note"),
  ]) {
    const result = executor.execute({
      timeline_id: "tlm_test",
      beat_id: op.beat_id,
      operation: op,
      sceneStore,
      registry,
      committedOps,
      journal,
    });
    assert.equal(result.ok, true);
    committedOps.add(op.operation_id);
  }

  const summary = summarizeAnnotationLifecycle(sceneStore.snapshot().entities_by_id);
  assert.equal(summary.active_annotation_count, 1);
  assert.equal(summary.compressed_annotation_count, 1);
  assert.equal(summary.passive_annotation_count, 0);
});
