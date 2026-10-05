import { describe, expect, it } from "vitest";
import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { deriveInstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  applyInstructionalLayout,
  COMPARISON_CENTER_X_RATIO,
} from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import {
  comparisonDividerCenterX,
  extractComparisonHints,
  partitionComparisonNodes,
  resolveComparisonDividerCenterX,
} from "@/lib/instruction-timeline-v3/teaching/comparisonSplit";
import type { InstructionTimelineV3 } from "@/lib/instruction-timeline-v3/types";

const WIDTH = 960;
const HEIGHT = 1040;

function node(
  id: string,
  hints?: RenderNodeProjection["teaching_hints"],
): RenderNodeProjection {
  return {
    projection_id: `prj:${id}`,
    source_entity_id: id,
    projection_kind: "node",
    projection_version: "1.0.0",
    layer: "nodes",
    z_index: 200,
    visible: true,
    viewport_box: { x: 0, y: 0, w: 180, h: 90 },
    render_meta: {},
    projection_hash: "sha256:test" as `sha256:${string}`,
    label: id,
    teaching_hints: hints,
  };
}

describe("comparison_split layout", () => {
  it("maps comparison_columns profile to comparison_split kind", () => {
    const timeline = {
      layout_metadata: { layout_profile: "comparison_columns" },
    } as InstructionTimelineV3;
    expect(deriveInstructionalLayoutKind(timeline)).toBe("comparison_split");
  });

  it("partitions CIR hints into aligned rows", () => {
    const ids = ["node_1", "node_2", "node_3", "node_4"];
    const part = partitionComparisonNodes(ids, (id) => {
      const map: Record<string, ReturnType<typeof extractComparisonHints>> = {
        node_1: { side: "left", tier: "header", order: 0 },
        node_2: { side: "right", tier: "header", order: 1 },
        node_3: { side: "left", tier: "row", order: 2 },
        node_4: { side: "right", tier: "row", order: 3 },
      };
      return map[id]!;
    });
    expect(part.leftHeader).toBe("node_1");
    expect(part.rightHeader).toBe("node_2");
    expect(part.rows).toEqual([{ left: "node_3", right: "node_4" }]);
  });

  it("falls back to index split when hints absent", () => {
    const ids = ["node_1", "node_2", "node_3", "node_4"];
    const part = partitionComparisonNodes(ids, (id) =>
      extractComparisonHints(id, undefined, ids.indexOf(id), ids.length),
    );
    expect(part.rows[0]?.left).toBe("node_1");
    expect(part.rows[0]?.right).toBe("node_3");
    expect(part.rows[1]?.left).toBe("node_2");
    expect(part.rows[1]?.right).toBe("node_4");
  });

  it("aligns row Y across left and right columns", () => {
    const nodes = [
      node("node_1", { comparison_side: "left", comparison_tier: "row" }),
      node("node_2", { comparison_side: "right", comparison_tier: "row" }),
      node("node_3", { comparison_side: "left", comparison_tier: "row" }),
    ];
    const laidOut = applyInstructionalLayout(nodes, WIDTH, HEIGHT, "comparison_split");
    const box = (id: string) =>
      laidOut.find((p) => p.source_entity_id === id)!.viewport_box;
    expect(box("node_1").y).toBe(box("node_2").y);
    expect(box("node_3").y).toBeGreaterThan(box("node_1").y);
    const dividerX = comparisonDividerCenterX(WIDTH);
    expect(dividerX).toBeLessThan(WIDTH * COMPARISON_CENTER_X_RATIO);
    expect(box("node_1").x + box("node_1").w).toBeLessThan(dividerX);
    expect(box("node_2").x).toBeGreaterThan(dividerX);
    const headerDivider = resolveComparisonDividerCenterX(WIDTH, laidOut);
    expect(headerDivider).toBeGreaterThan(box("node_1").x + box("node_1").w);
    expect(headerDivider).toBeLessThan(box("node_2").x);
  });

  it("keeps a lone left header in the left column (no horizontal recenter)", () => {
    const nodes = [node("node_0", { comparison_side: "left", comparison_tier: "header" })];
    const laidOut = applyInstructionalLayout(nodes, WIDTH, HEIGHT, "comparison_split");
    const box = laidOut.find((p) => p.source_entity_id === "node_0")!.viewport_box;
    expect(box.x).toBeLessThan(WIDTH * 0.35);
  });
    const nodes = [
      node("node_1", { comparison_side: "left", comparison_tier: "row" }),
      node("node_2", { comparison_side: "left", comparison_tier: "row" }),
      node("node_3", { comparison_side: "right", comparison_tier: "row" }),
    ];
    const laidOut = applyInstructionalLayout(nodes, WIDTH, HEIGHT, "comparison_split");
    const y1 = laidOut.find((p) => p.source_entity_id === "node_1")!.viewport_box.y;
    const y2 = laidOut.find((p) => p.source_entity_id === "node_2")!.viewport_box.y;
    const y3 = laidOut.find((p) => p.source_entity_id === "node_3")!.viewport_box.y;
    expect(y1).toBe(y3);
    expect(y2).toBeGreaterThan(y1);
  });
});
