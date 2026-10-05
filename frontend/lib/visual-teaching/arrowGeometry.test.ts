import test from "node:test";
import assert from "node:assert/strict";

import {
  arrowEndpointIds,
  clamp01Pt,
  distToSegment,
  hitArrow,
  isArrowEndpointAnchor,
  nextArrowConnectionId,
  shortenArrowLine,
} from "./arrowGeometry";
import { toolToRegionShape, type DrawTool } from "./drawGeometry";

test("region draw tools map to shapes; arrow is a separate draw tool", () => {
  const regionTools: Array<Exclude<DrawTool, "arrow">> = [
    "rectangle",
    "square",
    "circle",
  ];
  assert.equal(toolToRegionShape("rectangle"), "rect");
  assert.equal(toolToRegionShape("square"), "rect");
  assert.equal(toolToRegionShape("circle"), "ellipse");
  assert.ok(regionTools.every((t) => t !== "arrow"));
  const allTools: DrawTool[] = ["rectangle", "square", "circle", "arrow"];
  assert.ok(allTools.includes("arrow"));
});

test("nextArrowConnectionId allocates arrow_N sequentially", () => {
  assert.equal(nextArrowConnectionId([]), "arrow_1");
  assert.equal(nextArrowConnectionId(["arrow_1", "arrow_2"]), "arrow_3");
  assert.equal(nextArrowConnectionId(["connection_1", "arrow_1"]), "arrow_2");
});

test("arrowEndpointIds + ownership helpers", () => {
  const ids = arrowEndpointIds("arrow_2");
  assert.equal(ids.from, "arrow_2_from");
  assert.equal(ids.to, "arrow_2_to");
  assert.equal(isArrowEndpointAnchor("arrow_2_from", "arrow_2"), true);
  assert.equal(isArrowEndpointAnchor("arrow_2_to", "arrow_2"), true);
  assert.equal(isArrowEndpointAnchor("other", "arrow_2"), false);
});

test("hitArrow prefers endpoints then body", () => {
  const from = { x: 0.2, y: 0.2 };
  const to = { x: 0.8, y: 0.2 };
  assert.equal(hitArrow({ x: 0.2, y: 0.2 }, from, to), "from");
  assert.equal(hitArrow({ x: 0.8, y: 0.21 }, from, to), "to");
  assert.equal(hitArrow({ x: 0.5, y: 0.21 }, from, to), "body");
  assert.equal(hitArrow({ x: 0.5, y: 0.5 }, from, to), null);
});

test("distToSegment and clamp01Pt", () => {
  assert.ok(
    distToSegment({ x: 0.5, y: 0.3 }, { x: 0, y: 0.2 }, { x: 1, y: 0.2 }) < 0.11
  );
  const p = clamp01Pt({ x: -0.2, y: 1.4 });
  assert.equal(p.x, 0);
  assert.equal(p.y, 1);
});

test("shortenArrowLine leaves room for arrowhead", () => {
  const line = shortenArrowLine({ x: 0, y: 0 }, { x: 200, y: 0 });
  assert.ok(line);
  assert.ok(line!.x1 > 0);
  assert.ok(line!.x2 < 200);
  assert.equal(shortenArrowLine({ x: 0, y: 0 }, { x: 3, y: 0 }), null);
});
