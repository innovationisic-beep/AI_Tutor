import { describe, expect, it } from "vitest";

import {
  microTutorReplyText,
  playbackStartBeatIndex,
  shouldShowMicroTutorProse,
} from "./instructionOwnership";

describe("instructionOwnership", () => {
  it("reads playback_start_beat_index from metadata", () => {
    expect(playbackStartBeatIndex({ playback_start_beat_index: 4 })).toBe(4);
    expect(playbackStartBeatIndex(null)).toBe(0);
  });

  it("hides micro tutor prose when board timeline exists", () => {
    const messages = [
      { id: "1", role: "user" as const, kind: "text" as const, content: "I don't know" },
      {
        id: "2",
        role: "assistant" as const,
        kind: "text" as const,
        content: "should not show",
        instruction_timeline_v3: { timeline_id: "t1", beats: [] },
      },
    ];
    expect(shouldShowMicroTutorProse(messages, 1)).toBe(false);
    expect(microTutorReplyText(messages, 1)).toBe("");
  });
});
