/**
 * Concept-question thread — kept on the whiteboard panel, not in main chat.
 */

import type { ChatItem } from "@/hooks/useChat";

export type ConceptQuestionRecord = { index: number; text: string };

export type ConceptThreadItem =
  | { id: string; kind: "section"; heading: string }
  | { id: string; kind: "question"; text: string; index: number }
  | { id: string; kind: "answer"; text: string }
  | { id: string; kind: "tutor"; text: string; correct?: boolean };

const CONCEPT_ACTION_CONTENT = new Set([
  "i understand — next question",
  "i understand",
  "i still have a confusion",
]);

const FILL_IN_BLANK_RE = /_{3,}|____+/;

export function questionTextHasBlankMarker(text: string): boolean {
  return FILL_IN_BLANK_RE.test(text || "");
}

/** Resolve UI question mode; blank stem wins over stale MCQ options in meta. */
export function resolveConceptQuestionType(
  meta: {
    concept_question_type?: "mcq" | "fill_in_blank" | null;
    concept_question_options?: string[];
    concept_question_index?: number;
    micro_interaction_prompt?: string;
    current_question?: string;
  } | null | undefined,
  questionText: string
): "mcq" | "fill_in_blank" | null {
  const options = meta?.concept_question_options ?? [];
  const stem = (questionText || meta?.micro_interaction_prompt || "").trim();
  if (questionTextHasBlankMarker(stem)) {
    return "fill_in_blank";
  }
  if (meta?.concept_question_type === "fill_in_blank") {
    return "fill_in_blank";
  }
  if (meta?.concept_question_type === "mcq") {
    return "mcq";
  }
  if ((meta?.concept_question_index ?? 0) >= 2) {
    return "fill_in_blank";
  }
  if (options.length >= 2) {
    return "mcq";
  }
  return null;
}

export function isConceptQuestionMessage(m: ChatItem): boolean {
  return Boolean((m as { conceptQuestion?: boolean }).conceptQuestion);
}

/** Follow-up button clicks — not answers to a new numbered question. */
export function isConceptQuestionActionMessage(m: ChatItem): boolean {
  if (m.role !== "user" || m.kind !== "text") return false;
  if ((m as { conceptQuestionAction?: boolean }).conceptQuestionAction) {
    return true;
  }
  const raw = (m as { rawContent?: string }).rawContent?.trim();
  if (raw?.toLowerCase().startsWith("__action:")) return true;
  return CONCEPT_ACTION_CONTENT.has(m.content.trim().toLowerCase());
}

/** Free-text confusion during the follow-up loop — not a numbered answer. */
export function isConceptQuestionClarificationMessage(m: ChatItem): boolean {
  return Boolean(
    (m as { conceptQuestionClarification?: boolean }).conceptQuestionClarification
  );
}

export function filterChatMessages(messages: ChatItem[]): ChatItem[] {
  return messages.filter((m) => !isConceptQuestionMessage(m));
}

export function filterBoardMessages(
  messages: ChatItem[]
): Extract<ChatItem, { role: "assistant"; kind: "text" }>[] {
  return messages.filter(
    (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
      m.role === "assistant" &&
      m.kind === "text" &&
      !isConceptQuestionMessage(m)
  );
}

export function buildConceptThread(
  messages: ChatItem[],
  questionHistory: ConceptQuestionRecord[],
  options: {
    showPendingQuestion: boolean;
    pendingIndex: number;
  }
): ConceptThreadItem[] {
  const thread: ConceptThreadItem[] = [];
  const cq = messages.filter(isConceptQuestionMessage);
  const historyByIndex = new Map(questionHistory.map((q) => [q.index, q]));
  const shownQuestions = new Set<number>();
  /** Next numbered question expecting a typed student answer (0-based index). */
  let nextQuestionIndex = 0;

  const showQuestion = (index: number) => {
    if (shownQuestions.has(index)) return;
    const q = historyByIndex.get(index);
    if (!q) return;
    thread.push({
      id: `q-${q.index}`,
      kind: "question",
      text: q.text,
      index: q.index,
    });
    shownQuestions.add(index);
  };

  for (const m of cq) {
    if (m.role === "user" && m.kind === "text") {
      if (
        isConceptQuestionActionMessage(m) ||
        isConceptQuestionClarificationMessage(m)
      ) {
        thread.push({ id: m.id, kind: "answer", text: m.content });
        continue;
      }
      showQuestion(nextQuestionIndex);
      thread.push({ id: m.id, kind: "answer", text: m.content });
      nextQuestionIndex += 1;
      continue;
    }
    if (m.role === "assistant") {
      if (m.kind === "feedback") {
        thread.push({
          id: m.id,
          kind: "tutor",
          text: m.message,
          correct: m.correct,
        });
      } else if (m.kind === "text") {
        thread.push({ id: m.id, kind: "tutor", text: m.content });
      }
    }
  }

  if (options.showPendingQuestion) {
    showQuestion(options.pendingIndex);
  }

  return thread;
}
