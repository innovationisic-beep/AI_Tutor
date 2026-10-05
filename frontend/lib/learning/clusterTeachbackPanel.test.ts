import { describe, expect, it } from "vitest";
import type { ChatItem } from "@/hooks/useChat";
import {
  buildClusterTeachbackThread,
  filterBoardMessagesForClusterTeachback,
  filterClusterTeachbackFromChat,
  filterClusterTeachbackTutorFromChat,
} from "@/lib/learning/clusterTeachbackPanel";

describe("clusterTeachbackPanel", () => {
  it("routes tutor replies to board and hides them from chat", () => {
    const messages: ChatItem[] = [
      {
        id: "u1",
        role: "user",
        kind: "text",
        content: "They grow and breathe.",
        clusterTeachback: true,
      },
      {
        id: "t1",
        role: "assistant",
        kind: "text",
        content: "Good start — what about reproduction?",
        clusterTeachbackTutor: true,
      },
    ];

    expect(filterClusterTeachbackFromChat(messages)).toEqual([]);
    expect(filterClusterTeachbackTutorFromChat(messages)).toEqual([]);
    expect(filterBoardMessagesForClusterTeachback(messages).map((m) => m.id)).toEqual([
      "t1",
    ]);
  });

  it("builds chronological thread with questions, answers, and panel feedback", () => {
    const messages: ChatItem[] = [
      {
        id: "u1",
        role: "user",
        kind: "text",
        content: "Living things grow.",
        clusterTeachback: true,
      },
      {
        id: "t1",
        role: "assistant",
        kind: "feedback",
        message: "You scored 35 — let's try again.",
        correct: false,
        clusterTeachback: true,
      },
      {
        id: "u2",
        role: "user",
        kind: "text",
        content: "They grow, breathe, and reproduce.",
        clusterTeachback: true,
      },
    ];
    const history = [
      { id: "q0", text: "Explain the characteristics of living things." },
      { id: "q1", text: "Try again: explain all three characteristics." },
    ];
    const thread = buildClusterTeachbackThread(messages, history, {
      showPendingQuestion: false,
    });
    expect(thread.map((t) => t.kind)).toEqual([
      "question",
      "answer",
      "tutor",
      "question",
      "answer",
    ]);
    expect(thread[0].kind === "question" && thread[0].text).toBe(
      "Explain the characteristics of living things."
    );
    expect(thread[3].kind === "question" && thread[3].text).toBe(
      "Try again: explain all three characteristics."
    );
  });
});
