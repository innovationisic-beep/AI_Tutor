/**
 * Content-driven VTSE board frame.
 * Run: npx tsx --test lib/instruction-timeline-v3/teaching/boardDisplayFrame.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { RenderNodeProjection, RenderProjection } from "@/lib/instruction-timeline-v3/renderer/projectionTypes";
import { applyInstructionalLayout } from "@/lib/instruction-timeline-v3/teaching/instructionalLayout";
import type { InstructionalLayoutKind } from "@/lib/instruction-timeline-v3/teaching/deriveLayoutProfile";
import {
  BOARD_DISPLAY_PAD,
  BOARD_FIT_PADDING,
  HIERARCHY_BOARD_FIT_PADDING,
  PROCESS_BOARD_FIT_PADDING,
  boardDisplayFrame,
  computeBoardFitTransformFromBounds,
  contentBoundsFromProjections,
  mergeContentBounds,
  parseBoardFitTransform,
  type BoardFitPadding,
  type ContentBounds,
} from "@/lib/instruction-timeline-v3/teaching/boardViewportFit";
import {
  comparisonDividerForNodes,
  comparisonDividerGeometry,
  comparisonSplitStageBounds,
} from "@/lib/instruction-timeline-v3/teaching/comparisonSplit";
import { extendProcessStoryboardFitBounds } from "@/lib/instruction-timeline-v3/teaching/processStoryboardLayout";

const here = dirname(fileURLToPath(import.meta.url));
const WIDTH = 960;
const HEIGHT = 1040;

function node(
  id: string,
  hints?: RenderNodeProjection["teaching_hints"],
  visible = true,
): RenderNodeProjection {
  return {
    projection_id: `prj:${id}`,
    source_entity_id: id,
    projection_kind: "node",
    projection_version: "1.0.0",
    layer: "nodes",
    z_index: 200,
    visible,
    viewport_box: { x: 0, y: 0, w: 180, h: 90 },
    render_meta: {},
    projection_hash: "sha256:test",
    label: id,
    teaching_hints: hints,
  };
}

function fitPadding(kind: InstructionalLayoutKind): BoardFitPadding {
  if (kind === "flow_vertical_process") return PROCESS_BOARD_FIT_PADDING;
  if (kind === "hierarchy_root_children") return HIERARCHY_BOARD_FIT_PADDING;
  return BOARD_FIT_PADDING;
}

function frameFor(
  kind: InstructionalLayoutKind,
  projections: RenderProjection[],
  includeInvisible = false,
) {
  const laid = applyInstructionalLayout(projections, WIDTH, HEIGHT, kind);
  const ink = contentBoundsFromProjections(laid, { includeInvisible });
  assert.ok(ink);
  let fitBounds: ContentBounds = ink;
  if (kind === "comparison_split") {
    const stage = comparisonSplitStageBounds(WIDTH, HEIGHT, true);
    const merged = mergeContentBounds(ink, stage);
    assert.ok(merged);
    fitBounds = merged;
  }
  if (kind === "flow_vertical_process") {
    fitBounds = extendProcessStoryboardFitBounds(ink);
  }
  const align =
    kind === "flow_vertical_process" || kind === "hierarchy_root_children" ? "top" : "center";
  const transform = computeBoardFitTransformFromBounds(
    fitBounds,
    WIDTH,
    HEIGHT,
    fitPadding(kind),
    align,
    kind === "flow_vertical_process" ? 1 : undefined,
  );
  const fit = parseBoardFitTransform(transform);
  assert.ok(fit);
  let displayInk = ink;
  if (kind === "comparison_split") {
    const nodes = laid.filter(
      (p): p is RenderNodeProjection => p.projection_kind === "node",
    );
    const divider = comparisonDividerForNodes(WIDTH, nodes, displayInk.maxY, BOARD_DISPLAY_PAD);
    if (divider) {
      const withDivider = mergeContentBounds(displayInk, {
        minX: divider.centerX,
        minY: divider.topY,
        maxX: divider.centerX,
        maxY: divider.bottomY,
      });
      assert.ok(withDivider);
      displayInk = withDivider;
    }
  }
  const frame = boardDisplayFrame({ width: WIDTH, ink: displayInk, fit });
  return { laid, ink, displayInk, fit, transform, frame };
}

function comparisonNodes(rowCount: number): RenderNodeProjection[] {
  const nodes = [
    node("node_h_left", { comparison_side: "left", comparison_tier: "header" }),
    node("node_h_right", { comparison_side: "right", comparison_tier: "header" }),
  ];
  for (let i = 0; i < rowCount; i += 1) {
    nodes.push(
      node(`node_l_${i}`, { comparison_side: "left", comparison_tier: "row" }),
      node(`node_r_${i}`, { comparison_side: "right", comparison_tier: "row" }),
    );
  }
  return nodes;
}

test("one comparison row is short and many rows grow without using the canvas bottom", () => {
  const one = frameFor("comparison_split", comparisonNodes(1));
  const many = frameFor("comparison_split", comparisonNodes(4));
  assert.ok(one.frame.frameH < 500);
  assert.ok(many.frame.frameH > one.frame.frameH);
  assert.ok(many.frame.frameH < HEIGHT);
  const divider = comparisonDividerForNodes(WIDTH, one.laid.filter((p) => p.projection_kind === "node"), one.ink.maxY, BOARD_DISPLAY_PAD);
  assert.ok(divider);
  assert.equal(divider.bottomY, one.ink.maxY + BOARD_DISPLAY_PAD);
  assert.ok(divider.bottomY < HEIGHT - 48);
  assert.equal(comparisonDividerGeometry(WIDTH, true, 300).bottomY, 300);
});

test("a shallow hierarchy is shorter than a deeper one", () => {
  const shallow = frameFor("hierarchy_root_children", [
    node("node_1"),
    node("node_2"),
  ]);
  const deep = frameFor(
    "hierarchy_root_children",
    Array.from({ length: 9 }, (_, i) => node(`node_${i + 1}`)),
  );
  assert.ok(shallow.frame.frameH < deep.frame.frameH);
  assert.ok(shallow.frame.frameH < HEIGHT);
  assert.ok(deep.frame.frameH < HEIGHT);
});

test("a clustered grid frame starts at the grid and stays shorter than the canvas", () => {
  const frame = frameFor("grouped_cluster", [node("node_1"), node("node_2"), node("node_3")]);
  assert.ok(frame.frame.frameY > 0);
  assert.ok(frame.frame.frameH < HEIGHT);
  const top = frame.fit.translate.ty + frame.ink.minY * frame.fit.scale;
  assert.ok(Math.abs(frame.frame.frameY - Math.max(0, top - BOARD_DISPLAY_PAD)) < 0.01);
});

test("linear height follows the full lane when only an earlier step is visible", () => {
  const hints = { process_tier: "step" as const };
  const bothVisible = frameFor("flow_vertical_process", [
    node("node_1", hints),
    node("node_2", hints),
  ], true);
  const secondHidden = frameFor("flow_vertical_process", [
    node("node_1", hints, true),
    node("node_2", hints, false),
  ], true);
  assert.equal(secondHidden.frame.frameH, bothVisible.frame.frameH);
  assert.ok(secondHidden.frame.frameH > frameFor("flow_vertical_process", [node("node_1", hints)], true).frame.frameH);
  assert.ok(secondHidden.ink.maxY > contentBoundsFromProjections(secondHidden.laid, { includeInvisible: false })!.maxY);
});

test("a cycle frame covers the ring and is shorter than the canvas", () => {
  const frame = frameFor(
    "cycle_ring",
    ["node_1", "node_2", "node_3", "node_4"].map((id) => node(id)),
  );
  const top = frame.fit.translate.ty + frame.ink.minY * frame.fit.scale;
  const bottom = frame.fit.translate.ty + frame.ink.maxY * frame.fit.scale;
  assert.ok(frame.frame.frameY <= top);
  assert.ok(frame.frame.frameY + frame.frame.frameH >= bottom);
  assert.ok(frame.frame.frameH < HEIGHT);
  assert.ok(frame.ink.maxY - frame.ink.minY < HEIGHT);
});

test("a connector below its node stays inside the frame", () => {
  const ink = { minX: 40, minY: 80, maxX: 400, maxY: 420 };
  const fit = { scale: 1, translate: { tx: 20, ty: 10 } };
  const frame = boardDisplayFrame({ width: WIDTH, ink, fit });
  const connectorBottom = fit.translate.ty + 420 * fit.scale;
  assert.ok(frame.frameY + frame.frameH >= connectorBottom);
  assert.ok(frame.frameH < HEIGHT);
});

test("the same ink and fit produce the same frame", () => {
  const ink = { minX: 10, minY: 30, maxX: 800, maxY: 240 };
  const fit = { scale: 0.9, translate: { tx: 12, ty: 8 } };
  const a = boardDisplayFrame({ width: WIDTH, ink, fit });
  const b = boardDisplayFrame({ width: WIDTH, ink, fit });
  assert.deepEqual(a, b);
});

test("the viewBox keeps width 960 and does not refit scale from the cropped height", () => {
  const sample = frameFor("hierarchy_root_children", [node("node_1"), node("node_2")]);
  assert.match(sample.frame.viewBox, new RegExp(`^0 ${sample.frame.frameY} ${WIDTH} ${sample.frame.frameH}$`));
  assert.equal(sample.frame.width, WIDTH);
  const refit = computeBoardFitTransformFromBounds(
    sample.ink,
    WIDTH,
    HEIGHT,
    HIERARCHY_BOARD_FIT_PADDING,
    "top",
  );
  assert.equal(parseBoardFitTransform(refit)?.scale, sample.fit.scale);
  assert.notEqual(sample.frame.frameH, HEIGHT);
});

test("the whiteboard svg crops with the frame and the visual grid does not stretch the board", () => {
  const renderer = readFileSync(
    join(here, "../../../components/ai/timeline-v3/MinimalDeterministicRenderer.tsx"),
    "utf8",
  );
  const runtime = readFileSync(
    join(here, "../../../components/ai/timeline-v3/ProductionTimelineRuntimeView.tsx"),
    "utf8",
  );
  assert.match(renderer, /computeBoardFitTransformFromBounds\(bounds, width, height,/);
  assert.match(
    renderer,
    /aspectRatio: clipToViewport \? undefined : `\$\{width\} \/ \$\{displayFrame\.frameH\}`/,
  );
  assert.match(renderer, /viewBox=\{displayFrame\.viewBox\}/);
  assert.match(runtime, /alignItems: "start"/);
  const dividerSrc = readFileSync(join(here, "comparisonSplit.ts"), "utf8");
  const geometry = dividerSrc.slice(
    dividerSrc.indexOf("export function comparisonDividerGeometry"),
    dividerSrc.indexOf("export function comparisonDividerForNodes"),
  );
  assert.equal(geometry.includes("height - 48"), false);
});
