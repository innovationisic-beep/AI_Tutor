import type {
  ChatHistoryMessage,
  TutorActionButton,
  TutorResponse,
} from "./types";

function parseMeta(raw: string | null | undefined): {
  buttons?: TutorActionButton[];
  correct?: boolean;
} {
  if (!raw) return {};
  try {
    return JSON.parse(raw) as {
      buttons?: TutorActionButton[];
      correct?: boolean;
    };
  } catch {
    return {};
  }
}

/** Match backend quiz persistence: `message_type` quiz and/or intro + "\\n\\nQuestion: …" body. */
export function historyRowLooksLikeQuiz(row: ChatHistoryMessage): boolean {
  if (row.role !== "assistant") return false;
  const mt = row.message_type;
  if (mt === "quiz") return true;
  return /\n\nQuestion:\s*\S/.test(row.content);
}

export function splitQuizHistoryContent(content: string): {
  intro: string;
  question: string;
} {
  const parts = content.split(/\n\nQuestion:\s*/);
  const intro = parts[0]?.trim() ?? "";
  const question =
    parts.slice(1).join("\n\nQuestion: ").trim() || intro;
  return { intro, question };
}

export function syntheticTutorResponseFromHistoryRow(
  row: ChatHistoryMessage
): TutorResponse | null {
  if (row.role !== "assistant") return null;
  const t = row.message_type || "explanation";
  if (String(t).trim().toLowerCase() === "noop") return null;
  if (String(t).trim().toLowerCase() === "visual_teaching_sentence_ack") return null;
  if (String(t).trim().toLowerCase() === "visual_teaching_advance_ack") return null;
  const meta = parseMeta(row.metadata_json);
  const buttons = meta.buttons;
  const content = row.content;
  if (historyRowLooksLikeQuiz(row)) {
    const { intro, question } = splitQuizHistoryContent(content);
    return { type: "quiz", message: intro, question };
  }
  if (t === "feedback") {
    return {
      type: "feedback",
      message: content,
      correct: meta.correct ?? true,
      buttons,
    };
  }
  if (t === "start") {
    return {
      type: "start",
      message: content,
      buttons: buttons ?? [],
    };
  }
  if (t === "understanding_check") {
    return {
      type: "understanding_check",
      message: content,
      buttons: buttons ?? [],
    };
  }
  if (
    (t === "explanation" || !row.message_type) &&
    Array.isArray(buttons) &&
    buttons.length > 0
  ) {
    return {
      type: "understanding_check",
      message: content,
      buttons,
    };
  }
  if (t === "question_prompt") {
    return { type: "question_prompt", message: content, buttons };
  }
  if (t === "question_answered") {
    return {
      type: "question_answered",
      message: content,
      buttons: buttons ?? [],
    };
  }
  if (t === "completed") {
    return { type: "completed", message: content };
  }
  return {
    type: "explanation",
    message: content,
    buttons,
  };
}

export function mapHistoryRowToChatItem(
  row: ChatHistoryMessage,
  idx: number
) {
  const id = `h-${row.created_at}-${idx}`;
  if (row.role === "user") {
    return { id, role: "user", kind: "text", content: row.content };
  }
  const mt = (row.message_type || "").trim().toLowerCase();
  if (mt === "noop") {
    return null;
  }
  if (historyRowLooksLikeQuiz(row)) {
    const { intro, question } = splitQuizHistoryContent(row.content);
    return {
      id,
      role: "assistant",
      kind: "quiz_prompt",
      intro,
      question,
    };
  }
  const t = row.message_type;
  if (t === "feedback") {
    const meta = parseMeta(row.metadata_json);
    return {
      id,
      role: "assistant",
      kind: "feedback",
      message: row.content,
      correct: meta.correct ?? true,
    };
  }
  return { id, role: "assistant", kind: "text", content: row.content };
}
