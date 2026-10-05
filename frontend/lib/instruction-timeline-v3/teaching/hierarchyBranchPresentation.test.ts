import { describe, expect, it } from "vitest";

import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { hierarchyNodeDisplayLabel } from "@/lib/instruction-timeline-v3/teaching/hierarchyBranchPresentation";

function nodeProjection(
  label: string,
  identity?: string,
): Extract<RenderNodeProjection, { projection_kind: "node" }> {
  return {
    projection_kind: "node",
    projection_id: "p1",
    source_entity_id: "node_2",
    projection_version: "1.0.0",
    layer: "nodes",
    z_index: 0,
    visible: true,
    viewport_box: { x: 0, y: 0, w: 100, h: 40 },
    render_meta: {},
    projection_hash: "sha256:abc",
    label,
    teaching_hints: identity ? { hierarchy_identity: identity } : undefined,
  };
}

describe("hierarchyNodeDisplayLabel", () => {
  it("prefers hierarchy_identity over long label", () => {
    const p = nodeProjection(
      "Living things are things that grow and reproduce in many environments",
      "Grow",
    );
    expect(hierarchyNodeDisplayLabel(p)).toBe("Grow");
  });

  it("truncates very long labels without identity hint", () => {
    const p = nodeProjection(
      "Living things are things that grow and reproduce in many environments worldwide",
    );
    expect(hierarchyNodeDisplayLabel(p).split(/\s+/).length).toBeLessThanOrEqual(6);
  });
});
