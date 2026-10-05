import { describe, expect, it } from "vitest";

import type { ChatItem } from "@/hooks/useChat";
import {
  buildConceptThread,
  isConceptQuestionActionMessage,
  resolveConceptQuestionType,
} from "./conceptQuestionPanel";

describe("isConceptQuestionActionMessage", () => {
  it("detects actions from display label when flag is missing", () => {
    const m: ChatItem = {
      id: "u1",
      role: "user",
      kind: "text",
      content: "I understand — next question",
      conceptQuestion: true,
    };
    expect(isConceptQuestionActionMessage(m)).toBe(true);
  });

  it("detects actions from rawContent", () => {
    const m: ChatItem = {
      id: "u1",
      role: "user",
      kind: "text",
      content: "I understand — next question",
      rawContent: "__action:concept_q_next",
      conceptQuestion: true,
    };
    expect(isConceptQuestionActionMessage(m)).toBe(true);
  });
});

describe("resolveConceptQuestionType", () => {
  it("prefers fill-in when stem has a blank even if stale MCQ options exist", () => {
    expect(
      resolveConceptQuestionType(
        {
          concept_question_type: "mcq",
          concept_question_options: [
            "It can grow and develop",
            "It never needs to breathe",
          ],
          concept_question_index: 2,
        },
        "Living things can grow, reproduce, and _____?"
      )
    ).toBe("fill_in_blank");
  });

  it("uses mcq when type and options match", () => {
    expect(
      resolveConceptQuestionType(
        {
          concept_question_type: "mcq",
          concept_question_options: ["Rock", "Tree"],
          concept_question_index: 0,
        },
        "Which is living?"
      )
    ).toBe("mcq");
  });
});

describe("buildConceptThread", () => {
  it("places follow-up action before the next pending question", () => {
    const messages: ChatItem[] = [
      {
        id: "u1",
        role: "user",
        kind: "text",
        content: "grow",
        conceptQuestion: true,
      },
      {
        id: "u2",
        role: "user",
        kind: "text",
        content: "table",
        conceptQuestion: true,
      },
      {
        id: "u3",
        role: "user",
        kind: "text",
        content: "I understand — next question",
        conceptQuestion: true,
        conceptQuestionAction: true,
      },
    ];
    const history = [
      { index: 0, text: "Name one characteristic of living things." },
      { index: 1, text: "Is a table a living thing?" },
      { index: 2, text: "Can you name one thing that all living things can do?" },
    ];

    const thread = buildConceptThread(messages, history, {
      showPendingQuestion: true,
      pendingIndex: 2,
    });

    expect(threadLabels(thread)).toEqual([
      "Q1",
      "grow",
      "Q2",
      "table",
      "I understand — next question",
      "Q3",
    ]);
  });

  it("places follow-up action before Q3 even without conceptQuestionAction flag", () => {
    const messages: ChatItem[] = [
      {
        id: "u1",
        role: "user",
        kind: "text",
        content: "grow",
        conceptQuestion: true,
      },
      {
        id: "u2",
        role: "user",
        kind: "text",
        content: "table",
        conceptQuestion: true,
      },
      {
        id: "u3",
        role: "user",
        kind: "text",
        content: "I understand — next question",
        conceptQuestion: true,
      },
    ];
    const history = [
      { index: 0, text: "Question 1" },
      { index: 1, text: "Question 2" },
      { index: 2, text: "Question 3" },
    ];

    const thread = buildConceptThread(messages, history, {
      showPendingQuestion: true,
      pendingIndex: 2,
    });

    expect(threadLabels(thread)).toEqual([
      "Q1",
      "grow",
      "Q2",
      "table",
      "I understand — next question",
      "Q3",
    ]);
  });

  it("does not advance numbered questions for clarification text", () => {
    const messages: ChatItem[] = [
      {
        id: "u1",
        role: "user",
        kind: "text",
        content: "grow",
        conceptQuestion: true,
      },
      {
        id: "u2",
        role: "user",
        kind: "text",
        content: "table",
        conceptQuestion: true,
      },
      {
        id: "u3",
        role: "user",
        kind: "text",
        content: "I still have a confusion",
        conceptQuestion: true,
        conceptQuestionAction: true,
      },
      {
        id: "u4",
        role: "user",
        kind: "text",
        content: "Why is a rock not living?",
        conceptQuestion: true,
        conceptQuestionClarification: true,
      },
      {
        id: "u5",
        role: "user",
        kind: "text",
        content: "I understand — next question",
        conceptQuestion: true,
        conceptQuestionAction: true,
      },
    ];
    const history = [
      { index: 0, text: "Question 1" },
      { index: 1, text: "Question 2" },
      { index: 2, text: "Question 3" },
    ];

    const thread = buildConceptThread(messages, history, {
      showPendingQuestion: true,
      pendingIndex: 2,
    });

    expect(threadLabels(thread)).toEqual([
      "Q1",
      "grow",
      "Q2",
      "table",
      "I still have a confusion",
      "Why is a rock not living?",
      "I understand — next question",
      "Q3",
    ]);
  });
});

function threadLabels(
  thread: ReturnType<typeof buildConceptThread>
): string[] {
  return thread.map((t) =>
    t.kind === "question"
      ? `Q${t.index + 1}`
      : t.kind === "answer"
        ? t.text
        : "tutor"
  );
}
