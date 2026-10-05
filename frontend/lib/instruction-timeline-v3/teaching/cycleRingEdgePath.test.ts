import test from "node:test";
import assert from "node:assert/strict";

import { applyInstructionalLayout } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import {
  cycleRingEdgeMarkerReversed,
  cycleRingEdgePath,
  resolveCycleRingEdgeAnchors,
} from "@/lib/instruction-timeline-v3/teaching/cycleRingEdgePath";
import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

const WIDTH = 960;
const HEIGHT = 1040;
const MIN_EDGE_LEN = 18;

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

function assertCycleEdges(nodeCount: number): void {
  const ids = Array.from({ length: nodeCount }, (_, i) => `node_${i + 1}`);
  const laidOut = applyInstructionalLayout(ids.map(mockNode), WIDTH, HEIGHT, "cycle_ring");
  const byId = new Map(laidOut.map((n) => [n.source_entity_id, n.viewport_box]));
  const viewport = { width: WIDTH, height: HEIGHT };

  for (let i = 0; i < nodeCount; i++) {
    const fromId = ids[i];
    const toId = ids[(i + 1) % nodeCount];
    const fromN = byId.get(fromId)!;
    const toN = byId.get(toId)!;
    const { x1, y1, x2, y2 } = resolveCycleRingEdgeAnchors(fromN, toN);
    const len = Math.hypot(x2 - x1, y2 - y1);
    assert.ok(len >= MIN_EDGE_LEN, `${fromId}→${toId} anchor span ${len.toFixed(1)}px`);
    assert.ok(x1 > 1 && y1 > 1, `${fromId}→${toId} must not collapse to origin`);
    const path = cycleRingEdgePath(x1, y1, x2, y2, viewport);
    assert.match(path, /^M .+ C .+, .+, .+ .+$/);
    assert.equal(
      cycleRingEdgeMarkerReversed(x1, y1, x2, y2, viewport),
      false,
      `${fromId}→${toId} must not reverse marker`,
    );
  }
}

test("cycle ring edge paths follow clockwise chord direction on 4-node ring", () => {
  assertCycleEdges(4);
});

test("5-node ring bottom arc anchors span enough for edge render", () => {
  assertCycleEdges(5);
});
