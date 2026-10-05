import { describe, expect, it } from "vitest";

import {
  microInteractionPrompt,
  shouldShowMicroInteractionPrompt,
} from "./microInteraction";

describe("microInteraction", () => {
  it("prefers micro_interaction_prompt from meta", () => {
    expect(
      microInteractionPrompt({
        micro_interaction_prompt: "What is digestion?",
        current_question: "ignored",
      }),
    ).toBe("What is digestion?");
  });

  it("shows prompt only after explanation and during micro hold", () => {
    expect(
      shouldShowMicroInteractionPrompt(1, true, "What is digestion?"),
    ).toBe(false);
    expect(
      shouldShowMicroInteractionPrompt(1, false, "What is digestion?"),
    ).toBe(true);
    expect(shouldShowMicroInteractionPrompt(0, false, "Q?")).toBe(false);
    expect(shouldShowMicroInteractionPrompt(1, false, "")).toBe(false);
  });
});
