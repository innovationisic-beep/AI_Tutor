import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { mapTimestampsToChunkReveals, chunkIndexForPlaybackProgress, chunkWordEndOffsets } from "./phraseChunkTiming";

/** Mirrors cleanTextForSpeech without pulling the voice facade. */
function cleanTextForSpeech(text: string): string {
  return text
    .replace(/\*\*/g, "")
    .replace(/\*/g, "")
    .replace(/^- /gm, "")
    .replace(/`/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

describe("cleanTextForSpeech", () => {
  it("strips markdown markers", () => {
    assert.equal(cleanTextForSpeech("**Hello** *world*"), "Hello world");
    assert.equal(cleanTextForSpeech("- bullet\n`code`"), "bullet code");
  });
});

describe("mapTimestampsToChunkReveals", () => {
  it("maps word timestamps onto chunk indices", () => {
    const chunks = ["Hello world", "example"];
    const stamps = [
      { word: "Hello", start: 0.1, end: 0.3 },
      { word: "world", start: 0.35, end: 0.55 },
      { word: "example", start: 0.6, end: 0.9 },
    ];
    const reveals = mapTimestampsToChunkReveals(stamps, chunks);
    assert.deepEqual(
      reveals.map((r) => r.chunkIndex),
      [0, 1],
    );
    assert.equal(reveals[0].delayMs, 100);
    assert.equal(reveals[1].delayMs, 600);
  });

  it("returns empty when timestamps or chunks missing", () => {
    assert.deepEqual(mapTimestampsToChunkReveals([], ["a"]), []);
    assert.deepEqual(
      mapTimestampsToChunkReveals([{ word: "a", start: 0, end: 0.1 }], []),
      [],
    );
  });
});

describe("chunkIndexForPlaybackProgress", () => {
  it("weights longer chunks more of the timeline", () => {
    const ends = chunkWordEndOffsets(["one two three", "four"]);
    // 3 words then 1 word → first chunk covers 0–0.75
    assert.equal(chunkIndexForPlaybackProgress(0, ends), 0);
    assert.equal(chunkIndexForPlaybackProgress(0.5, ends), 0);
    assert.equal(chunkIndexForPlaybackProgress(0.8, ends), 1);
    assert.equal(chunkIndexForPlaybackProgress(1, ends), 1);
  });
});
