import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  MIN_NORM_SIZE,
  clampLabelBox,
  clientToNorm,
  defaultLabelBoxNear,
  dragToCircle,
  dragToRect,
  hitResizeHandle,
  isMeaningfulDrag,
  isNearSquare,
  moveEllipse,
  moveLabelBox,
  moveRect,
  oppositeCorner,
  pointInEllipse,
  pointInRect,
  rectHandles,
  resizeCircle,
  resizeLabelBox,
  resizeRect,
  toolToRegionShape,
} from "./drawGeometry";
import { fitLabelFontSize } from "./regionColors";
import { regionLabelFontSize } from "./VisualTeachingOverlay";
import {
  SVG_VIEWBOX,
  validateRegionGeometry,
  normalizeRegionGeometry,
} from "./index";

const here = dirname(fileURLToPath(import.meta.url));

test("toolToRegionShape: circle persists as ellipse; rect tools as rect", () => {
  assert.equal(toolToRegionShape("circle"), "ellipse");
  assert.equal(toolToRegionShape("rectangle"), "rect");
  assert.equal(toolToRegionShape("square"), "rect");
});

test("rectangle drag creates exact bounds", () => {
  const g = dragToRect({ x: 0.1, y: 0.2 }, { x: 0.5, y: 0.6 });
  assert.equal(g.x, 0.1);
  assert.equal(g.y, 0.2);
  assert.ok(Math.abs(g.w - 0.4) < 1e-9);
  assert.ok(Math.abs(g.h - 0.4) < 1e-9);
  assert.equal(validateRegionGeometry("rect", g).ok, true);
});

test("reverse-direction rectangle drag works", () => {
  const g = dragToRect({ x: 0.6, y: 0.7 }, { x: 0.2, y: 0.3 });
  assert.ok(Math.abs(g.x - 0.2) < 1e-9);
  assert.ok(Math.abs(g.y - 0.3) < 1e-9);
  assert.ok(Math.abs(g.w - 0.4) < 1e-9);
  assert.ok(Math.abs(g.h - 0.4) < 1e-9);
});

test("square preserves 1:1", () => {
  const g = dragToRect({ x: 0.2, y: 0.2 }, { x: 0.7, y: 0.4 }, { square: true });
  assert.ok(Math.abs(g.w - g.h) < 1e-9);
  assert.ok(g.w >= MIN_NORM_SIZE);
  assert.equal(isNearSquare(g), true);
});

test("circle preserves 1:1 via equal bounding box", () => {
  const g = dragToCircle({ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.35 });
  assert.ok(Math.abs(g.rx - g.ry) < 1e-9);
  assert.ok(g.rx >= MIN_NORM_SIZE / 2);
  // Corner-drag bbox: center is mid of square from (0.2,0.2).
  assert.ok(g.cx > 0.2 && g.cy > 0.2);
  assert.equal(validateRegionGeometry("ellipse", g).ok, true);
});

test("tiny drag is not meaningful commit", () => {
  assert.equal(
    isMeaningfulDrag({ x: 0.5, y: 0.5 }, { x: 0.51, y: 0.5 }),
    false
  );
  assert.equal(
    isMeaningfulDrag({ x: 0.5, y: 0.5 }, { x: 0.6, y: 0.5 }),
    true
  );
});

test("moving shape changes position only", () => {
  const base = { x: 0.1, y: 0.1, w: 0.2, h: 0.15 };
  const moved = moveRect(base, 0.3, 0.2);
  assert.equal(moved.w, base.w);
  assert.equal(moved.h, base.h);
  assert.ok(moved.x > base.x);
  assert.ok(moved.y > base.y);
  assert.ok(moved.x + moved.w <= 1 + 1e-9);

  const e0 = { cx: 0.4, cy: 0.4, rx: 0.1, ry: 0.1 };
  const e1 = moveEllipse(e0, 0.2, 0.1);
  assert.equal(e1.rx, e0.rx);
  assert.equal(e1.ry, e0.ry);
  assert.ok(e1.cx > e0.cx);
});

test("resizing rectangle changes expected edge; opposite stays fixed", () => {
  const initial = { x: 0.2, y: 0.2, w: 0.2, h: 0.2 };
  const fixed = oppositeCorner(initial, "se");
  assert.deepEqual(fixed, { x: 0.2, y: 0.2 });
  const resized = resizeRect(initial, "se", { x: 0.55, y: 0.6 });
  assert.ok(Math.abs(resized.x - 0.2) < 1e-9);
  assert.ok(Math.abs(resized.y - 0.2) < 1e-9);
  assert.ok(resized.w > 0.2);
  assert.ok(resized.h > 0.2);
});

test("resizing square/circle preserves aspect", () => {
  const sq = resizeRect(
    { x: 0.2, y: 0.2, w: 0.2, h: 0.2 },
    "se",
    { x: 0.7, y: 0.5 },
    { lockAspect: true }
  );
  assert.ok(Math.abs(sq.w - sq.h) < 1e-9);

  const c0 = { cx: 0.5, cy: 0.5, rx: 0.1, ry: 0.1 };
  const c1 = resizeCircle(c0, "se", { x: 0.75, y: 0.7 });
  assert.ok(Math.abs(c1.rx - c1.ry) < 1e-9);
  assert.ok(pointInEllipse({ x: c1.cx, y: c1.cy }, c1));
});

test("min-size clamp prevents collapse", () => {
  const tiny = dragToRect({ x: 0.5, y: 0.5 }, { x: 0.505, y: 0.505 });
  assert.ok(tiny.w >= MIN_NORM_SIZE);
  assert.ok(tiny.h >= MIN_NORM_SIZE);

  const shrunk = resizeRect(
    { x: 0.4, y: 0.4, w: 0.2, h: 0.2 },
    "se",
    { x: 0.401, y: 0.401 }
  );
  assert.ok(shrunk.w >= MIN_NORM_SIZE);
  assert.ok(shrunk.h >= MIN_NORM_SIZE);
});

test("bounds clamp keeps geometry in 0..1", () => {
  const moved = moveRect({ x: 0.8, y: 0.8, w: 0.3, h: 0.3 }, 0.5, 0.5);
  assert.ok(moved.x + moved.w <= 1 + 1e-9);
  assert.ok(moved.y + moved.h <= 1 + 1e-9);
  assert.ok(moved.x >= 0 && moved.y >= 0);

  const circle = dragToCircle({ x: 0.95, y: 0.95 }, { x: 1.2, y: 1.2 });
  assert.ok(circle.cx + circle.rx <= 1 + 1e-6);
  assert.ok(circle.cy + circle.ry <= 1 + 1e-6);
});

test("normalized geometry remains correct after normalize", () => {
  const g = dragToRect({ x: 0.1, y: 0.2 }, { x: 0.5, y: 0.55 });
  const n = normalizeRegionGeometry("rect", g) as typeof g;
  assert.ok(n.x >= 0 && n.x <= 1);
  assert.ok(n.w > 0 && n.w <= 1);
  const c = dragToCircle({ x: 0.3, y: 0.3 }, { x: 0.6, y: 0.6 });
  const nc = normalizeRegionGeometry("ellipse", c) as typeof c;
  assert.ok(Math.abs(nc.rx - nc.ry) < 1e-9);
});

test("clientToNorm uses fit-box content coords consistently", () => {
  const container = { left: 100, top: 50 };
  const box = { x: 10, y: 20, width: 200, height: 100 };
  // Pointer at content origin
  const origin = clientToNorm(110, 70, container, box);
  assert.deepEqual(origin, { x: 0, y: 0 });
  // Center of content box
  const mid = clientToNorm(210, 120, container, box);
  assert.ok(Math.abs(mid!.x - 0.5) < 1e-9);
  assert.ok(Math.abs(mid!.y - 0.5) < 1e-9);
  // Outside without clamp → null
  assert.equal(clientToNorm(50, 50, container, box), null);
  // Outside with clamp
  const clamped = clientToNorm(50, 50, container, box, { clamp: true });
  assert.equal(clamped!.x, 0);
  assert.equal(clamped!.y, 0);
});

test("resize handle hit-test works for small shapes", () => {
  const g = { x: 0.4, y: 0.4, w: 0.08, h: 0.08 };
  const handles = rectHandles(g);
  assert.equal(hitResizeHandle({ x: 0.4, y: 0.4 }, handles), "nw");
  assert.equal(hitResizeHandle({ x: 0.48, y: 0.48 }, handles), "se");
});

test("polygon geometry still validates (legacy data)", () => {
  const points = [
    { x: 0.1, y: 0.1 },
    { x: 0.4, y: 0.15 },
    { x: 0.3, y: 0.4 },
  ];
  assert.equal(validateRegionGeometry("polygon", { points }).ok, true);
});

test("label font fits inside chrome box (no overflow)", () => {
  const long = fitLabelFontSize(80, 30, 40);
  const short = fitLabelFontSize(200, 40, 4);
  assert.ok(long.fontSize > 0);
  assert.ok(long.padX * 2 < 80);
  assert.ok(long.padY * 2 < 30);
  assert.ok(short.fontSize >= long.fontSize);
  // Clip + fit: font never exceeds box height.
  assert.ok(long.fontSize <= 30);
  assert.ok(short.fontSize <= 40);
});

test("label box move/resize stay normalized", () => {
  const box = defaultLabelBoxNear({ x: 0.5, y: 0.5 }, 10);
  assert.ok(box.w >= 0.12);
  assert.ok(box.h >= 0.05);
  const moved = moveLabelBox(box, 0.2, -0.1);
  assert.ok(moved.x + moved.w <= 1 + 1e-9);
  assert.ok(moved.y >= 0);
  const resized = resizeLabelBox(box, "se", {
    x: box.x + 0.3,
    y: box.y + 0.12,
  });
  assert.ok(resized.w > box.w);
  assert.ok(resized.h > box.h);
  const clamped = clampLabelBox({ x: -0.1, y: 0.9, w: 0.8, h: 0.3 });
  assert.ok(clamped.y + clamped.h <= 1 + 1e-9);
  assert.ok(clamped.x >= 0);
});

test("region label font remains readable", () => {
  const size = regionLabelFontSize();
  assert.ok(size >= 28);
  assert.ok(size <= SVG_VIEWBOX * 0.05);
});

test("AuthImage disables native drag", () => {
  const src = readFileSync(
    join(here, "../../components/media/AuthImage.tsx"),
    "utf8"
  );
  assert.match(src, /draggable=\{false\}/);
  assert.match(src, /onDragStart/);
  assert.match(src, /preventDefault/);
});

test("VisualTeachingStage: image is non-draggable canvas during authoring", () => {
  const src = readFileSync(join(here, "VisualTeachingStage.tsx"), "utf8");
  assert.match(src, /pointer-events-none/);
  assert.match(src, /setPointerCapture/);
  assert.match(src, /select-none/);
  assert.match(src, /clientToNorm/);
  assert.match(src, /onDragStart/);
});

test("pointInRect helper", () => {
  const g = { x: 0.2, y: 0.2, w: 0.3, h: 0.3 };
  assert.equal(pointInRect({ x: 0.35, y: 0.35 }, g), true);
  assert.equal(pointInRect({ x: 0.1, y: 0.1 }, g), false);
});

test("arrow label_box resolves authored box and can be resized like regions", async () => {
  const { resolveConnectionLabelBox } = await import("./geometry");
  const authored = resolveConnectionLabelBox(
    {
      connection_id: "arrow_1",
      label: "flow",
      label_box: { x: 0.2, y: 0.3, w: 0.25, h: 0.08 },
    },
    { x: 0.1, y: 0.5 },
    { x: 0.9, y: 0.5 }
  );
  assert.equal(authored.x, 0.2);
  assert.equal(authored.y, 0.3);
  assert.ok(authored.w >= 0.12);
  const resized = resizeLabelBox(authored, "se", {
    x: authored.x + 0.35,
    y: authored.y + 0.14,
  });
  assert.ok(resized.w > authored.w);
  assert.ok(resized.h > authored.h);
});
