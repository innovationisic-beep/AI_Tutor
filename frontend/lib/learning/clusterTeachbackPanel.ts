import type { ChatItem } from "@/hooks/useChat";

export type ClusterTeachbackThreadItem =
  | { id: string; kind: "section"; heading: string }
  | { id: string; kind: "question"; text: string }
  | { id: string; kind: "answer"; text: string }
  | { id: string; kind: "tutor"; text: string; correct?: boolean };

export type ClusterTeachbackQuestionRecord = { id: string; text: string };

export function isClusterTeachbackMessage(m: ChatItem): boolean {
  return Boolean((m as { clusterTeachback?: boolean }).clusterTeachback);
}

export function isClusterTeachbackTutorMessage(m: ChatItem): boolean {
  return Boolean((m as { clusterTeachbackTutor?: boolean }).clusterTeachbackTutor);
}

export function filterClusterTeachbackTutorFromChat(messages: ChatItem[]): ChatItem[] {
  return messages.filter((m) => !isClusterTeachbackTutorMessage(m));
}

export function filterClusterTeachbackFromChat(messages: ChatItem[]): ChatItem[] {
  return messages.filter(
    (m) => !isClusterTeachbackMessage(m) && !isClusterTeachbackTutorMessage(m)
  );
}

export function filterBoardMessagesForClusterTeachback(
  messages: ChatItem[]
): ChatItem[] {
  return messages.filter(
    (m): m is Extract<ChatItem, { role: "assistant"; kind: "text" }> =>
      m.role === "assistant" &&
      m.kind === "text" &&
      !isClusterTeachbackMessage(m)
  );
}

export function buildClusterTeachbackThread(
  messages: ChatItem[],
  questionHistory: ClusterTeachbackQuestionRecord[],
  options: { showPendingQuestion: boolean }
): ClusterTeachbackThreadItem[] {
  const thread: ClusterTeachbackThreadItem[] = [];
  const tagged = messages.filter(isClusterTeachbackMessage);
  const shownQuestionIds = new Set<string>();
  let nextQuestionIndex = 0;

  const showQuestion = (index: number) => {
    const q = questionHistory[index];
    if (!q || shownQuestionIds.has(q.id)) return;
    thread.push({ id: q.id, kind: "question", text: q.text });
    shownQuestionIds.add(q.id);
  };

  for (const m of tagged) {
    if (m.role === "user" && m.kind === "text") {
      showQuestion(nextQuestionIndex);
      thread.push({ id: m.id, kind: "answer", text: m.content });
      nextQuestionIndex += 1;
      continue;
    }
    if (m.role === "assistant" && m.kind === "feedback") {
      thread.push({
        id: m.id,
        kind: "tutor",
        text: m.message,
        correct: m.correct,
      });
    }
  }

  if (options.showPendingQuestion) {
    showQuestion(nextQuestionIndex);
  }

  return thread;
}
