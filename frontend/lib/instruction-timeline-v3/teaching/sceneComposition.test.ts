import test from "node:test";
import assert from "node:assert/strict";

import { applyInstructionalLayout } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import {
  boxesOverlap,
  buildCompositionContext,
  clusterObstaclesFromProjections,
  composeAnnotations,
  edgeObstacleBulge,
} from "@/lib/instruction-timeline-v3/teaching/sceneComposition";
import { ownerColumnBand } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";
import type {
  RenderAnnotationProjection,
  RenderNodeProjection,
} from "@/lib/instruction-timeline-v3/renderer/projectionTypes";

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

function mockAnn(targetId: string, text: string, projSuffix = ""): RenderAnnotationProjection {
  return {
    projection_id: `ann_${targetId}${projSuffix}`,
    source_entity_id: `ann_src_${targetId}${projSuffix}`,
    projection_kind: "annotation",
    projection_version: "1.0.0",
    layer: "annotations",
    z_index: 20,
    visible: true,
    viewport_box: { x: 0, y: 0, w: 200, h: 48 },
    render_meta: {},
    projection_hash: "sha256:mock",
    target_id: targetId,
    text,
  };
}

function laidOut(
  nodes: RenderNodeProjection[],
  anns: RenderAnnotationProjection[],
  kind: Parameters<typeof applyInstructionalLayout>[3],
) {
  return applyInstructionalLayout([...nodes, ...anns], WIDTH, HEIGHT, kind);
}

test("composeAnnotations is deterministic for identical input", () => {
  const nodes = [mockNode("node_1"), mockNode("node_2"), mockNode("node_3")];
  const laidNodes = applyInstructionalLayout(nodes, WIDTH, HEIGHT, "flow_left_right");
  const nodeMap = new Map(
    laidNodes
      .filter((p) => p.projection_kind === "node")
      .map((n) => [n.source_entity_id, n.viewport_box]),
  );
  const ctx = buildCompositionContext("flow_left_right", WIDTH, HEIGHT, ["node_1", "node_2", "node_3"], nodeMap);
  const anns = [mockAnn("node_1", "Step one"), mockAnn("node_2", "Step two longer text")];
  const a = composeAnnotations(anns, ctx);
  const b = composeAnnotations(anns, ctx);
  assert.deepEqual(
    a.map((x) => x.viewport_box),
    b.map((x) => x.viewport_box),
  );
});

test("grouped_cluster: each annotation stays in owner column band below its node", () => {
  const nodes = [
    mockNode("node_1"),
    mockNode("node_2"),
    mockNode("node_3"),
    mockNode("node_4"),
    mockNode("node_5"),
  ];
  const anns = [
    mockAnn("node_1", "Next, living things breathe."),
    mockAnn("node_2", "First, living things grow."),
    mockAnn("node_3", "Finally, living things reproduce."),
    mockAnn("node_4", "For example, humans and plants."),
    mockAnn("node_5", "What are living things?"),
  ];
  const laid = laidOut(nodes, anns, "grouped_cluster");
  const nodeBoxes = new Map(
    laid.filter((p) => p.projection_kind === "node").map((n) => [n.source_entity_id, n.viewport_box]),
  );

  for (const ann of laid.filter((p) => p.projection_kind === "annotation")) {
    const tid = ann.target_id!;
    const node = nodeBoxes.get(tid)!;
    const band = ownerColumnBand(node);
    const ab = ann.viewport_box;
    assert.ok(ab.y >= node.y + node.h - 2, `${tid} annotation should sit below owner node`);
    assert.ok(ab.x >= band.left - 4, `${tid} annotation should stay in owner column`);
    assert.ok(ab.x + ab.w <= band.right + 4, `${tid} annotation should stay in owner column`);
  }
});

test("grouped_cluster: annotation horizontally overlaps only its owner node", () => {
  const nodes = [mockNode("node_1"), mockNode("node_2"), mockNode("node_3")];
  const anns = [
    mockAnn("node_1", "Explain breathe"),
    mockAnn("node_2", "Explain grow"),
    mockAnn("node_3", "Explain reproduce"),
  ];
  const laid = laidOut(nodes, anns, "grouped_cluster");
  const nodeBoxes = new Map(
    laid.filter((p) => p.projection_kind === "node").map((n) => [n.source_entity_id, n.viewport_box]),
  );
  for (const ann of laid.filter((p) => p.projection_kind === "annotation")) {
    const owner = nodeBoxes.get(ann.target_id!)!;
    const ab = ann.viewport_box;
    const overlapsOwner =
      ab.x + ab.w > owner.x + 8 && ab.x < owner.x + owner.w - 8;
    assert.ok(overlapsOwner, `${ann.target_id} card must sit under its owner column`);
  }
});

test("hierarchy layout: annotations avoid node overlap", () => {
  const nodes = [mockNode("node_1"), mockNode("node_2"), mockNode("node_3"), mockNode("node_4")];
  const anns = [
    mockAnn("node_1", "Root concept overview for the lesson"),
    mockAnn("node_2", "Child detail A"),
    mockAnn("node_3", "Child detail B"),
    mockAnn("node_4", "Child detail C"),
  ];
  const laid = laidOut(nodes, anns, "hierarchy_root_children");
  const nodeBoxes = laid.filter((p) => p.projection_kind === "node").map((p) => p.viewport_box);
  const annBoxes = laid.filter((p) => p.projection_kind === "annotation").map((p) => p.viewport_box);
  for (const ann of annBoxes) {
    for (const node of nodeBoxes) {
      assert.equal(boxesOverlap(ann, node, 4), false);
    }
  }
});

test("clusterObstacles merge node with owned annotations", () => {
  const nodes = [mockNode("node_1"), mockNode("node_2")];
  const anns = [mockAnn("node_1", "Owned explanation text")];
  const laid = laidOut(nodes, anns, "flow_left_right");
  const obstacles = clusterObstaclesFromProjections(laid);
  assert.ok(obstacles.length >= 2);
  const node1 = laid.find((p) => p.source_entity_id === "node_1" && p.projection_kind === "node")!;
  const ann1 = laid.find((p) => p.projection_kind === "annotation")!;
  const ob = obstacles[0];
  assert.ok(ob.y <= node1.viewport_box.y);
  assert.ok(ob.y + ob.h >= ann1.viewport_box.y + ann1.viewport_box.h - 20);
});

test("edgeObstacleBulge increases when samples hit cluster obstacles", () => {
  const obstacles = [{ x: 300, y: 400, w: 220, h: 200 }];
  const bulge = edgeObstacleBulge(200, 500, 700, 500, obstacles);
  assert.ok(bulge > 0);
});
