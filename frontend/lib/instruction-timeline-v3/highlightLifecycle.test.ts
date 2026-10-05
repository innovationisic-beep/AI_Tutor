import assert from "node:assert/strict";
import test from "node:test";

import {
  buildHighlightEntity,
  highlightEmphasis,
  retireActiveHighlights,
  summarizeHighlightLifecycle,
} from "@/lib/instruction-timeline-v3/highlightLifecycle";
import type { HighlightEntityOp } from "@/lib/instruction-timeline-v3/types";
import { createDefaultOperationRegistry } from "@/lib/instruction-timeline-v3/operationRegistry";
import { OperationExecutor } from "@/lib/instruction-timeline-v3/executor";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { CommitJournal } from "@/lib/instruction-timeline-v3/commitJournal";

function highlightOp(
  id: string,
  opNum: number,
  beatId: string,
  targetId: string,
  ttl_ms?: number,
): HighlightEntityOp {
  return {
    operation_id: `op_${String(opNum).padStart(6, "0")}`,
    op_type: "highlight_entity",
    beat_id: beatId,
    depends_on: [],
    payload: {
      highlight_id: id,
      target_ids: [targetId],
      style_token: "concept-highlight",
      ...(ttl_ms != null ? { ttl_ms } : {}),
    },
    sync: { execution_mode: "instant_commit", binding_mode: "on_segment_start" },
    reversibility: { reversible: true, inverse_op_type: null },
    preconditions: [],
    postconditions: [],
    determinism_key: `sha256:${id}`,
  };
}

test("retireActiveHighlights marks prior overlays retired without deactivating nodes", () => {
  const entities: Record<string, import("@/lib/instruction-timeline-v3/types").SceneEntity> = {
    node_a: {
      entity_id: "node_a",
      entity_type: "Node",
      kind: "primitive",
      version: 1,
      label: "A",
      spatial: { x: 0, y: 0, w: 10, h: 10 },
      semantic: { role: "concept" },
      render: { layer: 1 },
      lifecycle: { state: "active", created_by_op: "op_1" },
    },
    hl_1: buildHighlightEntity(
      highlightOp("hl_1", 2, "beat_0", "node_a"),
    ),
  };

  retireActiveHighlights(entities, "op_3");
  assert.equal(highlightEmphasis(entities.hl_1 as import("@/lib/instruction-timeline-v3/types").HighlightEntity), "retired");
  assert.equal(entities.node_a.lifecycle.state, "active");
});

test("summarizeHighlightLifecycle counts active vs retired", () => {
  const hl1 = buildHighlightEntity(highlightOp("hl_1", 1, "b", "n"));
  const hl2 = buildHighlightEntity(highlightOp("hl_2", 2, "b", "n", 800));
  const entities: Record<string, import("@/lib/instruction-timeline-v3/types").SceneEntity> = {
    hl_1: { ...hl1, semantic: { role: "focus", payload: { emphasis: "retired" } } },
    hl_2: hl2,
  };
  const summary = summarizeHighlightLifecycle(entities);
  assert.equal(summary.active_highlight_count, 1);
  assert.equal(summary.retired_highlight_count, 1);
  assert.equal(summary.current_focus_highlight, "hl_2");
  assert.equal(summary.ttl_ms_by_highlight.hl_2, 800);
});

test("executor retires prior highlight when a new highlight_entity commits", () => {
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

  const hl1 = highlightOp("hl_1", 2, "beat_0000", "node_a");
  const hl2 = highlightOp("hl_2", 3, "beat_0001", "node_a");

  for (const op of [nodeOp, hl1, hl2]) {
    const result = executor.execute({
      timeline_id: "tlm_test",
      beat_id: op.beat_id,
      operation: op,
      sceneStore,
      registry,
      committedOps,
      journal,
    });
    assert.equal(result.ok, true, `op ${op.operation_id} failed`);
    committedOps.add(op.operation_id);
  }

  const entities = sceneStore.snapshot().entities_by_id;
  assert.equal(highlightEmphasis(entities.hl_1 as import("@/lib/instruction-timeline-v3/types").HighlightEntity), "retired");
  assert.equal(highlightEmphasis(entities.hl_2 as import("@/lib/instruction-timeline-v3/types").HighlightEntity), "active");

  const summary = summarizeHighlightLifecycle(entities);
  assert.equal(summary.active_highlight_count, 1);
  assert.equal(summary.retired_highlight_count, 1);
  assert.equal(summary.current_focus_highlight, "hl_2");
  assert.equal(entities.node_a.lifecycle.state, "active");
});
