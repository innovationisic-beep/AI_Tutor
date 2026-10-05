/**
 * Whiteboard auto-scroll follow rules.
 * Run: npx tsx --test lib/learning/boardAutoScroll.test.ts
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  BOARD_NEAR_BOTTOM_PX,
  buildBoardScrollFollowKey,
  distanceFromBottom,
  isNearBottom,
  shouldScrollOnContentGrowth,
  shouldScrollOnFollowKeyChange,
  stickAfterUserScroll,
} from "./boardAutoScroll";

function metrics(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number
) {
  return { scrollHeight, scrollTop, clientHeight };
}

describe("near-bottom detection", () => {
  it("treats within threshold as near bottom", () => {
    // height 1000, client 400 → max scrollTop 600; at 500 → dist 100
    assert.equal(distanceFromBottom(metrics(1000, 500, 400)), 100);
    assert.equal(isNearBottom(metrics(1000, 500, 400), 140), true);
    assert.equal(isNearBottom(metrics(1000, 400, 400), 140), false);
  });

  it("resumes stick when user returns near bottom", () => {
    assert.equal(stickAfterUserScroll(metrics(1000, 590, 400)), true);
    assert.equal(stickAfterUserScroll(metrics(1000, 200, 400)), false);
  });

  it("uses default ~140px threshold", () => {
    assert.equal(BOARD_NEAR_BOTTOM_PX, 140);
  });
});

describe("follow key", () => {
  it("changes when a new board item appears", () => {
    const a = buildBoardScrollFollowKey({ lastBoardItemId: "b1" });
    const b = buildBoardScrollFollowKey({ lastBoardItemId: "b2" });
    assert.notEqual(a, b);
  });

  it("changes when a chat / timeline episode appears", () => {
    const a = buildBoardScrollFollowKey({ timelineKeys: ["convo-1"] });
    const b = buildBoardScrollFollowKey({
      timelineKeys: ["convo-1", "convo-2"],
    });
    assert.notEqual(a, b);
  });

  it("changes when thinking row appears or clears", () => {
    const a = buildBoardScrollFollowKey({
      lastBoardItemId: "b1",
      thinkingVisible: false,
    });
    const b = buildBoardScrollFollowKey({
      lastBoardItemId: "b1",
      thinkingVisible: true,
    });
    assert.notEqual(a, b);
  });

  it("changes when Concept Check / stage panel opens", () => {
    const a = buildBoardScrollFollowKey({
      lastBoardItemId: "b1",
      panelKey: null,
    });
    const b = buildBoardScrollFollowKey({
      lastBoardItemId: "b1",
      panelKey: "concept-check",
    });
    assert.notEqual(a, b);
  });

  it("does not change on silent meta-only / unchanged structure", () => {
    const a = buildBoardScrollFollowKey({
      timelineKeys: ["convo-1"],
      lastBoardItemId: "b1",
      thinkingVisible: false,
      panelKey: null,
    });
    const b = buildBoardScrollFollowKey({
      timelineKeys: ["convo-1"],
      lastBoardItemId: "b1",
      thinkingVisible: false,
      panelKey: null,
    });
    assert.equal(a, b);
  });
});

describe("scroll decisions", () => {
  it("new item while near bottom → scroll", () => {
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: true,
        prevKey: "board:b1",
        nextKey: "board:b2",
      }),
      true
    );
  });

  it("user scrolled up → no forced scroll", () => {
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: false,
        prevKey: "board:b1",
        nextKey: "board:b2",
      }),
      false
    );
  });

  it("user returns near bottom → auto-follow resumes on next key", () => {
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: true,
        prevKey: "board:b1",
        nextKey: "board:b2",
      }),
      true
    );
  });

  it("same key (streaming tokens) does not fire key-change scroll", () => {
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: true,
        prevKey: "board:b1|think:0",
        nextKey: "board:b1|think:0",
      }),
      false
    );
  });

  it("streaming growth follows only while stuck near bottom", () => {
    assert.equal(
      shouldScrollOnContentGrowth({ enabled: true, stickToBottom: true }),
      true
    );
    assert.equal(
      shouldScrollOnContentGrowth({ enabled: true, stickToBottom: false }),
      false
    );
  });

  it("disabled during restore / suppress → no scroll", () => {
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: false,
        stickToBottom: true,
        prevKey: "a",
        nextKey: "b",
      }),
      false
    );
    assert.equal(
      shouldScrollOnContentGrowth({ enabled: false, stickToBottom: true }),
      false
    );
  });

  it("thinking → real response keeps follow when stuck", () => {
    const thinking = buildBoardScrollFollowKey({
      lastBoardItemId: "b1",
      thinkingVisible: true,
    });
    const real = buildBoardScrollFollowKey({
      lastBoardItemId: "b2",
      thinkingVisible: false,
    });
    assert.equal(
      shouldScrollOnFollowKeyChange({
        enabled: true,
        stickToBottom: true,
        prevKey: thinking,
        nextKey: real,
      }),
      true
    );
  });
});
