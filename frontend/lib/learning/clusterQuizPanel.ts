import type { ChatItem } from "@/hooks/useChat";
import type { TutorSessionMeta } from "@/lib/types";

export type ClusterQuizRecord = { index: number; text: string };

export type ClusterThreadItem =
  | { id: string; kind: "section"; heading: string }
  | { id: string; kind: "question"; index: number; text: string }
  | { id: string; kind: "answer"; text: string }
  | { id: string; kind: "tutor"; text: string; correct?: boolean };

export const CLUSTER_QUESTIONS_PER_CLUSTER = 3;

const CLUSTER_ACTION_CONTENT = new Set([
  "i understand — next question",
  "i understand",
  "i still have a confusion",
]);

export function resolveClusterQuizType(
  meta: TutorSessionMeta | null | undefined,
  promptText: string
): "mcq" | "descriptive" | null {
  const declared = meta?.cluster_quiz_type;
  if (declared === "mcq") return "mcq";
  if (declared === "descriptive") return "descriptive";
  const options = meta?.cluster_quiz_options ?? [];
  if (options.length >= 2) return "mcq";
  if ((meta?.cluster_quiz_index ?? 0) >= 2) return "mcq";
  if (promptText.trim()) return "descriptive";
  return null;
}

export function isClusterQuizMessage(m: ChatItem): boolean {
  return Boolean((m as { clusterQuiz?: boolean }).clusterQuiz);
}

export function isClusterQuizActionMessage(m: ChatItem): boolean {
  if (m.role !== "user" || m.kind !== "text") return false;
  if ((m as { clusterQuizAction?: boolean }).clusterQuizAction) {
    return true;
  }
  const raw = (m as { rawContent?: string }).rawContent?.trim();
  if (raw?.toLowerCase().startsWith("__action:")) return true;
  return CLUSTER_ACTION_CONTENT.has(m.content.trim().toLowerCase());
}

export function isClusterQuizClarificationMessage(m: ChatItem): boolean {
  return Boolean(
    (m as { clusterQuizClarification?: boolean }).clusterQuizClarification
  );
}

export function filterClusterQuizFromChat(messages: ChatItem[]): ChatItem[] {
  return messages.filter((m) => !isClusterQuizMessage(m));
}

export function filterBoardMessagesForClusterQuiz(messages: ChatItem[]): ChatItem[] {
  return messages.filter(
    (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
      m.role === "assistant" &&
      m.kind === "text" &&
      !isClusterQuizMessage(m)
  );
}

export function buildClusterQuizThread(
  messages: ChatItem[],
  questionHistory: ClusterQuizRecord[],
  options: {
    showPendingQuestion: boolean;
    pendingIndex: number;
  }
): ClusterThreadItem[] {
  const thread: ClusterThreadItem[] = [];
  const cq = messages.filter(isClusterQuizMessage);
  const historyByIndex = new Map(questionHistory.map((q) => [q.index, q]));
  const shownQuestions = new Set<number>();
  let nextQuestionIndex = 0;

  const showQuestion = (index: number) => {
    if (shownQuestions.has(index)) return;
    const q = historyByIndex.get(index);
    if (!q) return;
    thread.push({
      id: `cq-q-${q.index}`,
      kind: "question",
      text: q.text,
      index: q.index,
    });
    shownQuestions.add(index);
  };

  for (const m of cq) {
    if (m.role === "user" && m.kind === "text") {
      if (
        isClusterQuizActionMessage(m) ||
        isClusterQuizClarificationMessage(m)
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

export function relabelClusterNextButton(
  buttons: { id: string; label: string }[],
  questionIndex: number | undefined
): { id: string; label: string }[] {
  if (
    questionIndex == null ||
    questionIndex < CLUSTER_QUESTIONS_PER_CLUSTER - 1
  ) {
    return buttons;
  }
  return buttons.map((b) =>
    b.id === "cluster_q_next" ? { ...b, label: "I understand" } : b
  );
}
