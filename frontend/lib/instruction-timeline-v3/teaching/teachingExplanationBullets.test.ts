import test from "node:test";
import assert from "node:assert/strict";

import {
  formatTeachingExplanationBullets,
  teachingExplanationPlain,
  wrapTeachingExplanationForRow,
  wrapTeachingExplanationLines,
} from "@/lib/instruction-timeline-v3/teaching/teachingExplanationBullets";

test("paragraph becomes sentence bullets", () => {
  const input =
    "Living things grow. They become larger over time. Growth helps organisms develop and mature.";
  const bullets = formatTeachingExplanationBullets(input);
  assert.deepEqual(bullets, [
    "• Living things grow",
    "• They become larger over time",
    "• Growth helps organisms develop and mature",
  ]);
});

test("caps at five bullets", () => {
  const input = Array.from({ length: 8 }, (_, i) => `Point ${i + 1}.`).join(" ");
  assert.equal(formatTeachingExplanationBullets(input).length, 5);
});

test("preserves already-bulleted text", () => {
  const input = "• First idea\n• Second idea";
  assert.deepEqual(formatTeachingExplanationBullets(input), ["• First idea", "• Second idea"]);
});

test("wrapTeachingExplanationLines keeps bullets on separate rows", () => {
  const lines = wrapTeachingExplanationLines(
    "One. Two. Three.",
    40,
  );
  assert.equal(lines.length, 3);
  assert.ok(lines.every((l) => l.startsWith("•")));
});

test("wrapTeachingExplanationForRow respects max line budget", () => {
  const lines = wrapTeachingExplanationForRow("A. B. C. D. E. F.", 30, 3);
  assert.equal(lines.length, 3);
});

test("teachingExplanationPlain joins with newlines", () => {
  const plain = teachingExplanationPlain("Alpha. Beta.");
  assert.equal(plain, "• Alpha\n• Beta");
});
