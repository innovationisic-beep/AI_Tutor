import test from "node:test";
import assert from "node:assert/strict";

import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";
import { SceneProjectionEngine } from "@/lib/instruction-timeline-v3/renderer/projection";
import { computeProjectionDiff } from "@/lib/instruction-timeline-v3/renderer/projectionDiff";
import { defaultViewport, toViewportCoordinates } from "@/lib/instruction-timeline-v3/renderer/viewport";
import { MinimalRendererRuntime } from "@/lib/instruction-timeline-v3/renderer/rendererRuntime";
import { RuntimeEventBus } from "@/lib/instruction-timeline-v3/eventBus";

function sceneWithNode() {
  const store = new SceneStore(
    {
      node_1: {
        entity_id: "node_1",
        entity_type: "Node",
        kind: "primitive",
        version: 1,
        label: "Seed",
        spatial: { x: 10, y: 20, w: 120, h: 48 },
        semantic: { role: "concept" },
        render: { layer: 1, style_token: "node_primary", visible: true },
        lifecycle: { state: "active", created_by_op: "bootstrap" },
      },
    },
    ["node_1"],
  );
  return store.snapshot();
}

test("projection generation is deterministic", () => {
  const scene = sceneWithNode();
  const engine = new SceneProjectionEngine();
  const viewport = defaultViewport(800, 600);
  const a = engine.project({ scene, viewport, at: "2026-01-01T00:00:00.000Z" });
  const b = engine.project({ scene, viewport, at: "2026-01-01T00:00:01.000Z" });
  assert.equal(a.projection_hash, b.projection_hash);
});

test("layer ordering remains stable", () => {
  const scene = sceneWithNode();
  const runtime = new MinimalRendererRuntime();
  const frame = runtime.render(scene, "2026-01-01T00:00:00.000Z");
  const ids = frame.snapshot.projections.map((p) => p.projection_id);
  const sorted = [...ids].sort((a, b) => a.localeCompare(b));
  assert.deepEqual(ids, sorted);
});

test("projection diff detects updates deterministically", () => {
  const scene = sceneWithNode();
  const engine = new SceneProjectionEngine();
  const viewport = defaultViewport();
  const a = engine.project({ scene, viewport, at: "2026-01-01T00:00:00.000Z" });

  const changedStore = new SceneStore(scene.entities_by_id, scene.root_order);
  changedStore.apply((draft) => {
    const entity = draft.entities_by_id.node_1;
    if (entity && entity.entity_type === "Node") entity.label = "Growth";
  });
  const b = engine.project({
    scene: changedStore.snapshot(),
    viewport,
    at: "2026-01-01T00:00:01.000Z",
  });
  const diff = computeProjectionDiff(a, b);
  assert.equal(diff.updated.length, 1);
  assert.equal(diff.added.length, 0);
  assert.equal(diff.removed.length, 0);
});

test("viewport transform is deterministic", () => {
  const viewport = { ...defaultViewport(1000, 800), pan_x: 10, pan_y: 20, scale: 2 };
  const box = toViewportCoordinates({ x: 20, y: 40, w: 10, h: 5 }, viewport);
  assert.deepEqual(box, { x: 20, y: 40, w: 20, h: 10 });
});

test("projection hash stability across replay-like reruns", () => {
  const scene = sceneWithNode();
  const viewport = defaultViewport();
  const engine1 = new SceneProjectionEngine();
  const engine2 = new SceneProjectionEngine();
  const a = engine1.project({ scene, viewport, at: "2026-01-01T00:00:00.000Z" });
  const b = engine2.project({ scene, viewport, at: "2026-01-01T00:00:00.000Z" });
  assert.equal(a.projection_hash, b.projection_hash);
});

test("renderer runtime emits projection lifecycle events deterministically", () => {
  const bus = new RuntimeEventBus();
  const runtime = new MinimalRendererRuntime({ eventBus: bus });
  runtime.render(sceneWithNode(), "2026-01-01T00:00:00.000Z");
  const eventTypes = bus.getEvents().map((e) => e.type);
  assert.ok(eventTypes.includes("projection_generated"));
  assert.ok(eventTypes.includes("projection_diff_computed"));
  assert.ok(eventTypes.includes("render_layer_updated"));
});
