import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { RenderNodeProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import {
  buildComparisonRowUnits,
  comparisonRowCharsPerLine,
  reflowComparisonRowUnits,
  shouldUseComparisonRowRenderer,
  wrapComparisonRowText,
} from "@/lib/instruction-timeline-v3/teaching/comparisonRowRenderer";

function node(
  id: string,
  side: "left" | "right",
  tier: "header" | "row",
  pairIndex: number,
  label: string,
  detail?: string,
  dimension?: string,
): RenderNodeProjection {
  const dim = dimension ?? "Reliability";
  const rowDetail = detail ?? label;
  return {
    projection_id: `prj:${id}`,
    source_entity_id: id,
    projection_kind: "node",
    projection_version: "1.0.0",
    layer: "nodes",
    z_index: 1,
    visible: true,
    viewport_box: side === "left" ? { x: 28, y: 140 + pairIndex * 120, w: 400, h: 96 } : { x: 480, y: 140 + pairIndex * 120, w: 400, h: 96 },
    render_meta: {},
    projection_hash: "sha256:test" as `sha256:${string}`,
    label,
    row_detail: `${dim}: ${rowDetail}`,
    teaching_hints: {
      comparison_side: side,
      comparison_tier: tier,
      pair_index: pairIndex,
      semantic_role: tier === "header" ? "column_header" : "comparison_row",
      comparison_dimension: tier === "row" ? dim : undefined,
    },
  };
}

describe("comparisonRowRenderer", () => {
  it("builds generic paired row units", () => {
    const projections = [
      node("node_0", "left", "header", 0, "TCP"),
      node("node_1", "right", "header", 0, "UDP"),
      node("node_2", "left", "row", 0, "Reliable", "TCP ensures reliable delivery.", "Reliability"),
      node("node_3", "right", "row", 0, "Fast", "UDP prioritizes speed over reliability.", "Reliability"),
    ];
    const { units, stats } = buildComparisonRowUnits(projections, "node_2");
    assert.equal(units.length, 1);
    assert.equal(units[0]?.phase, "active");
    assert.equal(units[0]?.left.text, "Reliability: TCP ensures reliable delivery.");
    assert.equal(units[0]?.right.text, "Reliability: UDP prioritizes speed over reliability.");
    assert.equal(stats.comparison_render_mode, "row_aligned");
  });

  it("activates comparison row renderer for comparison_split teaching mode", () => {
    const projections = [node("node_2", "left", "row", 0, "A", "A detail")];
    assert.equal(
      shouldUseComparisonRowRenderer("comparison_split", "teaching", projections),
      true,
    );
    assert.equal(
      shouldUseComparisonRowRenderer("flow_left_right", "teaching", projections),
      false,
    );
  });

  it("wraps long row prose deterministically", () => {
    const lines = wrapComparisonRowText(
      "Humans need food and water to survive in natural environments.",
      20,
      3,
    );
    assert.ok(lines.length >= 2);
    assert.ok(lines.every((line) => line.length <= 20));
  });

  it("derives wrap width from cell box width", () => {
    const narrow = comparisonRowCharsPerLine(220);
    const wide = comparisonRowCharsPerLine(404);
    assert.ok(wide > narrow);
    assert.ok(wide >= 48);
  });

  it("reflow grows row height for long prose", () => {
    const long =
      "Humans excel at creative thinking, understanding others' feelings, and adapting to new situations. " +
      "We can write stories, paint, and comfort a friend when they are sad.";
    const projections = [
      node("node_0", "left", "header", 0, "Humans"),
      node("node_1", "right", "header", 0, "Robots"),
      node("node_2", "left", "row", 0, "Creative", long, "Creativity"),
      node("node_3", "right", "row", 0, "Repeat", "Robots repeat tasks.", "Creativity"),
    ];
    const { units } = buildComparisonRowUnits(projections, "node_2");
    const reflowed = reflowComparisonRowUnits(units);
    const left = reflowed[0]?.left;
    assert.ok(left);
    assert.ok(left.box.h > 112);
    const lines = wrapComparisonRowText(long, comparisonRowCharsPerLine(left.box.w), 14);
    assert.ok(lines.length >= 3);
  });

  it("skips orphan single-side rows", () => {
    const projections = [
      node("node_2", "right", "row", 0, "Fast", "UDP only row.", "Speed"),
    ];
    const { units, stats } = buildComparisonRowUnits(projections, null);
    assert.equal(units.length, 0);
    assert.equal(stats.skipped_incomplete_rows, 1);
  });

  it("hides row until both sides visible", () => {
    const left = node("node_2", "left", "row", 0, "Reliable", "TCP detail.", "Reliability");
    const right = node("node_3", "right", "row", 0, "Fast", "UDP detail.", "Reliability");
    left.visible = true;
    right.visible = false;
    const { units } = buildComparisonRowUnits([left, right], "node_2");
    assert.equal(units.length, 1);
    assert.equal(units[0]?.phase, "active");
    assert.ok(units[0]?.left);
    assert.equal(units[0]?.right, null);
  });
});
