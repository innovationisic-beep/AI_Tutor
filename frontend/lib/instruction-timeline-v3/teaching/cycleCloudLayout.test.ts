import assert from "node:assert/strict";
import test from "node:test";

import {
  composeCycleCloudAnnotations,
  placeCycleCloudBox,
  resolveCycleCloudPlacement,
} from "@/lib/instruction-timeline-v3/teaching/cycleCloudLayout";
import { CYCLE_RING_CY_RATIO } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import type { AnnotationProjection } from "@/lib/instruction-timeline-v3/teaching/teachingClusters";

const WIDTH = 960;
const HEIGHT = 1040;
const CX = WIDTH / 2;
const CY = HEIGHT * CYCLE_RING_CY_RATIO;

function mockAnn(id: string, targetId: string, text: string): AnnotationProjection {
  return {
    projection_id: id,
    source_entity_id: `src_${id}`,
    projection_kind: "annotation",
    projection_version: "1.0.0",
    layer: "annotations",
    z_index: 20,
    visible: true,
    viewport_box: { x: 0, y: 0, w: 160, h: 72 },
    render_meta: {},
    projection_hash: "sha256:mock",
    text,
    target_id: targetId,
    annotation_phase: "active",
    annotation_kind: "pedagogical",
  };
}

test("resolveCycleCloudPlacement maps ring quadrants", () => {
  assert.equal(resolveCycleCloudPlacement(CX, CY - 100, { cx: CX, cy: CY }), "above");
  assert.equal(resolveCycleCloudPlacement(CX, CY + 100, { cx: CX, cy: CY }), "below");
  assert.equal(resolveCycleCloudPlacement(CX - 120, CY, { cx: CX, cy: CY }), "outside_left");
  assert.equal(resolveCycleCloudPlacement(CX + 120, CY, { cx: CX, cy: CY }), "outside_right");
});

test("placeCycleCloudBox attaches above and below node with clearance", () => {
  const node = { x: 400, y: 200, w: 160, h: 72 };
  const above = placeCycleCloudBox(node, 228, 100, "above");
  assert.ok(above.y + above.h + 8 <= node.y, "above cloud must sit above node");
  const below = placeCycleCloudBox(node, 228, 80, "below");
  assert.ok(below.y >= node.y + node.h);
});

test("composeCycleCloudAnnotations places clouds outside ring not in bottom grid", () => {
  const nodeIds = ["n1", "n2", "n3", "n4"];
  const nodeBoxes = new Map(
    nodeIds.map((id, i) => {
      const theta = -Math.PI / 2 + (2 * Math.PI * i) / 4;
      const r = 180;
      const w = 160;
      const h = 72;
      const ncx = CX + r * Math.cos(theta);
      const ncy = CY + r * Math.sin(theta);
      return [
        id,
        { x: Math.round(ncx - w / 2), y: Math.round(ncy - h / 2), w, h },
      ] as const;
    }),
  );
  const annotations = nodeIds.map((id, i) => mockAnn(`ann_${i}`, id, `Explain ${id}`));
  const laidOut = composeCycleCloudAnnotations(annotations, {
    width: WIDTH,
    height: HEIGHT,
    nodeIds,
    nodeBoxes,
    cycleCenter: { cx: CX, cy: CY },
  });

  for (const ann of laidOut) {
    assert.ok(ann.teaching_hints?.cycle_cloud_placement);
    const node = nodeBoxes.get(ann.target_id!)!;
    const cloudCy = ann.viewport_box.y + ann.viewport_box.h / 2;
    const nodeCy = node.y + node.h / 2;
    const placement = ann.teaching_hints!.cycle_cloud_placement!;
    if (placement === "above") {
      assert.ok(ann.viewport_box.y + ann.viewport_box.h <= node.y + 4);
    }
    if (placement === "below") {
      assert.ok(ann.viewport_box.y >= node.y + node.h - 4);
    }
    if (placement === "outside_left") {
      assert.ok(ann.viewport_box.x + ann.viewport_box.w <= node.x + 4);
    }
    if (placement === "outside_right") {
      assert.ok(ann.viewport_box.x >= node.x + node.w - 4);
    }
    // Cloud center should not sit closer to ring core than its node (away from center).
    const distCloud = Math.hypot(
      ann.viewport_box.x + ann.viewport_box.w / 2 - CX,
      cloudCy - CY,
    );
    const distNode = Math.hypot(node.x + node.w / 2 - CX, nodeCy - CY);
    assert.ok(distCloud >= distNode - 12);
  }
});
