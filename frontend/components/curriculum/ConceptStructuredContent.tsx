"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createAdminQuestion,
  createQuestion,
  deleteAdminQuestion,
  deleteTeacherQuestion,
  updateAdminQuestion,
  updateTeacherQuestion,
} from "@/lib/api";
import { getConceptUsage } from "@/lib/api/curriculumStructure";
import type { ConceptUsage, CurriculumConcept, CurriculumTopicSource } from "@/lib/types";

type QuestionKind = "descriptive" | "mcq" | "fill_blank";
type QuizStage = "concept_check" | "cluster_quiz";
type ModalStep = "closed" | "pick_stage" | "form";

type ConceptStructuredContentProps = {
  token: string;
  topicId: string;
  topicSource: CurriculumTopicSource;
  concept: CurriculumConcept;
  onNotify: (message: string, variant?: "ok" | "err") => void;
};

function stageLabel(stage: string | null | undefined): string {
  if (stage === "concept_check") return "Concept check";
  if (stage === "cluster_quiz") return "Cluster quiz";
  return "Untagged";
}

function typeLabel(t: string | null | undefined): string {
  if (t === "mcq") return "MCQ";
  if (t === "fill_in_blank") return "Fill-in";
  if (t === "descriptive") return "Descriptive";
  return "Question";
}

const FILL_BLANK_MARKER = "_____";
const FILL_BLANK_RE = /_{3,}|\[blank\]|\{\{\s*blank\s*\}\}/i;

/** Normalize any blank marker to the canonical _____ teachers should use. */
function ensureFillBlankStem(text: string): string {
  const t = text.trim();
  if (!t) return `Complete: ${FILL_BLANK_MARKER}`;
  if (FILL_BLANK_RE.test(t)) {
    return t.replace(FILL_BLANK_RE, FILL_BLANK_MARKER);
  }
  return `${t.replace(/[.!?]*$/, "")} ${FILL_BLANK_MARKER}.`;
}

export function ConceptStructuredContent({
  token,
  topicId,
  topicSource,
  concept,
  onNotify,
}: ConceptStructuredContentProps) {
  const [usage, setUsage] = useState<ConceptUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [modalStep, setModalStep] = useState<ModalStep>("closed");
  const [quizStage, setQuizStage] = useState<QuizStage | null>(null);
  const [questionKind, setQuestionKind] = useState<QuestionKind>("mcq");
  const [questionText, setQuestionText] = useState("");
  const [questionExplanation, setQuestionExplanation] = useState("");
  const [mcqOptions, setMcqOptions] = useState(["", ""]);
  const [mcqCorrect, setMcqCorrect] = useState("");
  const [fillAnswer, setFillAnswer] = useState("");
  const [editingQuestionId, setEditingQuestionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const questionTextRef = useRef<HTMLTextAreaElement | null>(null);
  const questionCursorRef = useRef<{ start: number; end: number }>({
    start: 0,
    end: 0,
  });

  function rememberQuestionCursor() {
    const el = questionTextRef.current;
    if (!el) return;
    questionCursorRef.current = {
      start: el.selectionStart ?? el.value.length,
      end: el.selectionEnd ?? el.value.length,
    };
  }

  function insertBlankAtCursor() {
    const el = questionTextRef.current;
    const value = questionText;
    const { start, end } = questionCursorRef.current;
    const safeStart = Math.max(0, Math.min(start, value.length));
    const safeEnd = Math.max(safeStart, Math.min(end, value.length));
    const next =
      value.slice(0, safeStart) + FILL_BLANK_MARKER + value.slice(safeEnd);
    setQuestionText(next);
    const caret = safeStart + FILL_BLANK_MARKER.length;
    questionCursorRef.current = { start: caret, end: caret };
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  const reloadUsage = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getConceptUsage(token, concept.id, topicSource);
      setUsage(data);
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Failed to load concept usage", "err");
      setUsage(null);
    } finally {
      setLoading(false);
    }
  }, [token, concept.id, topicSource, onNotify]);

  useEffect(() => {
    void reloadUsage();
  }, [reloadUsage]);

  const cc = usage?.concept_check;
  const cq = usage?.cluster_quiz;
  const mcqFull = (cc?.mcq_count ?? 0) >= (cc?.mcq_cap ?? 2);
  const fillFull = (cc?.fill_in_blank_count ?? 0) >= (cc?.fill_in_blank_cap ?? 1);
  const clusterFull = (cq?.remaining ?? 0) <= 0;

  const conceptCheckQuestions = useMemo(
    () => (usage?.questions ?? []).filter((q) => q.quiz_stage === "concept_check"),
    [usage]
  );
  const clusterQuizQuestions = useMemo(
    () => (usage?.questions ?? []).filter((q) => q.quiz_stage === "cluster_quiz"),
    [usage]
  );

  function resetQuestionForm() {
    setQuestionText("");
    setQuestionExplanation("");
    setMcqOptions(["", ""]);
    setMcqCorrect("");
    setFillAnswer("");
    setQuestionKind("mcq");
    setEditingQuestionId(null);
    setQuizStage(null);
    setModalStep("closed");
  }

  function openAddModal() {
    setEditingQuestionId(null);
    setQuestionText("");
    setQuestionExplanation("");
    setMcqOptions(["", ""]);
    setMcqCorrect("");
    setFillAnswer("");
    setQuizStage(null);
    setModalStep("pick_stage");
  }

  function selectStage(stage: QuizStage) {
    setQuizStage(stage);
    if (stage === "concept_check") {
      if (!mcqFull) setQuestionKind("mcq");
      else if (!fillFull) setQuestionKind("fill_blank");
      else {
        onNotify("All concept-check slots are full for this concept", "err");
        return;
      }
    } else {
      if (clusterFull && !editingQuestionId) {
        onNotify(
          "This cluster already has 3 cluster-quiz questions. Remove one from a concept in this cluster first.",
          "err"
        );
        return;
      }
      setQuestionKind("descriptive");
    }
    setModalStep("form");
  }

  function buildQuestionPayload() {
    const text = questionText.trim();
    if (!text) throw new Error("Question text cannot be empty");
    if (!quizStage) throw new Error("Choose Concept check or Cluster quiz");

    if (questionKind === "mcq") {
      const options = mcqOptions.map((o) => o.trim()).filter(Boolean);
      if (options.length < 2) throw new Error("MCQ requires at least 2 options");
      const correct = mcqCorrect.trim();
      if (!correct || !options.includes(correct)) {
        throw new Error("Select a valid correct answer from options");
      }
      return {
        question_text: text,
        options,
        correct_answer: correct,
        explanation: questionExplanation.trim() || correct,
        difficulty_level: concept.difficulty_level || "medium",
        question_type: "mcq" as const,
        quiz_stage: quizStage,
      };
    }
    if (questionKind === "fill_blank") {
      if (quizStage !== "concept_check") {
        throw new Error("Fill-in questions are only for concept check");
      }
      const answer = fillAnswer.trim();
      if (!answer) throw new Error("Fill-in-blank requires a correct answer");
      const blankText = ensureFillBlankStem(text);
      return {
        question_text: blankText,
        options: [] as string[],
        correct_answer: answer,
        explanation: questionExplanation.trim() || answer,
        difficulty_level: concept.difficulty_level || "medium",
        question_type: "fill_in_blank" as const,
        quiz_stage: quizStage,
      };
    }
    if (quizStage === "concept_check") {
      throw new Error("Concept check questions must be MCQ or fill-in");
    }
    return {
      question_text: text,
      options: [] as string[],
      correct_answer: null as string | null,
      explanation: questionExplanation.trim() || "See lesson board.",
      difficulty_level: concept.difficulty_level || "medium",
      question_type: "descriptive" as const,
      quiz_stage: quizStage,
    };
  }

  async function saveStructuredQuestion() {
    setBusy(true);
    try {
      const q = buildQuestionPayload();
      if (editingQuestionId) {
        const updateBody = { ...q, structured: true };
        if (topicSource === "catalog") {
          await updateAdminQuestion(token, editingQuestionId, updateBody);
        } else {
          await updateTeacherQuestion(token, editingQuestionId, updateBody);
        }
        onNotify("Question updated");
      } else {
        const createPayload = {
          topic_id: topicId,
          concept_id: concept.id,
          structured: true,
          ...q,
        };
        if (topicSource === "catalog") {
          await createAdminQuestion(token, createPayload);
        } else {
          await createQuestion(token, createPayload);
        }
        onNotify("Question created");
      }
      resetQuestionForm();
      await reloadUsage();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Question save failed", "err");
    } finally {
      setBusy(false);
    }
  }

  async function removeQuestion(questionId: string) {
    if (!confirm("Delete this structured question?")) return;
    setBusy(true);
    try {
      if (topicSource === "catalog") {
        await deleteAdminQuestion(token, questionId);
      } else {
        await deleteTeacherQuestion(token, questionId);
      }
      onNotify("Question deleted");
      if (editingQuestionId === questionId) resetQuestionForm();
      await reloadUsage();
    } catch (e) {
      onNotify(e instanceof Error ? e.message : "Delete question failed", "err");
    } finally {
      setBusy(false);
    }
  }

  function startEdit(q: ConceptUsage["questions"][number]) {
    setEditingQuestionId(q.id);
    const stage = (q.quiz_stage as QuizStage | null) ?? null;
    setQuizStage(stage ?? "concept_check");
    const opts = q.options ?? [];
    const qtype = q.question_type;
    if (qtype === "mcq" || opts.length >= 2) {
      setQuestionKind("mcq");
      setMcqOptions(opts.length ? opts : ["", ""]);
      setMcqCorrect(q.correct_answer ?? "");
    } else if (qtype === "fill_in_blank" || (q.correct_answer && !opts.length)) {
      setQuestionKind("fill_blank");
      setFillAnswer(q.correct_answer ?? "");
    } else {
      setQuestionKind("descriptive");
    }
    setQuestionText(q.question_text ?? "");
    setQuestionExplanation(q.explanation ?? "");
    setModalStep("form");
  }

  function renderQuestionList(
    title: string,
    rows: ConceptUsage["questions"],
    emptyMsg: string
  ) {
    return (
      <div className="mt-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {title} ({rows.length})
        </h4>
        {rows.length === 0 ? (
          <p className="mt-1 text-xs text-slate-500">{emptyMsg}</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {rows.map((q) => (
              <li
                key={q.id}
                className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-700"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {typeLabel(q.question_type)}
                    </span>
                    <span className="text-slate-700 dark:text-slate-200">
                      {q.question_text ?? "Question"}
                    </span>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      className="text-violet-600 hover:underline disabled:opacity-50"
                      onClick={() => startEdit(q)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      className="text-red-600 hover:underline disabled:opacity-50"
                      onClick={() => void removeQuestion(q.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const modalOpen = modalStep !== "closed";

  return (
    <div className="mt-6 space-y-6 border-t border-slate-200 pt-4 dark:border-slate-700">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">Questions</h3>
          <p className="mt-1 text-xs text-slate-500">
            Tag each question for Concept check (2 MCQ + 1 fill-in) or Cluster quiz (up to 3 per
            cluster). For fill-in, use exactly 5 underscores:{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] dark:bg-slate-800">
              _____
            </code>
            . Runtime key:{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] dark:bg-slate-800">
              {concept.canonical_runtime_key}
            </code>
          </p>
          {usage ? (
            <p className="mt-1 text-xs text-slate-500">
              Concept check: {cc?.mcq_count ?? 0}/{cc?.mcq_cap ?? 2} MCQ,{" "}
              {cc?.fill_in_blank_count ?? 0}/{cc?.fill_in_blank_cap ?? 1} fill-in · Cluster quiz:{" "}
              {cq?.used ?? 0}/{cq?.cap ?? 3} used
            </p>
          ) : null}
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={openAddModal}
          className="shrink-0 rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          Add question
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-slate-500">Loading questions…</p>
      ) : usage ? (
        <div>
          {renderQuestionList(
            "Concept check",
            conceptCheckQuestions,
            "No concept-check questions yet."
          )}
          {renderQuestionList(
            "Cluster quiz (this concept)",
            clusterQuizQuestions,
            "No cluster-quiz questions on this concept yet."
          )}
        </div>
      ) : null}

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-xl dark:border-slate-700 dark:bg-slate-900"
          >
            <div className="mb-3 flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                {editingQuestionId
                  ? "Edit question"
                  : modalStep === "pick_stage"
                    ? "Add question — choose stage"
                    : `Add ${quizStage ? stageLabel(quizStage).toLowerCase() : ""} question`}
              </h4>
              <button
                type="button"
                disabled={busy}
                onClick={resetQuestionForm}
                className="text-xs text-slate-500 hover:underline"
              >
                Close
              </button>
            </div>

            {modalStep === "pick_stage" ? (
              <div className="space-y-3">
                <button
                  type="button"
                  disabled={busy || (mcqFull && fillFull)}
                  onClick={() => selectStage("concept_check")}
                  className="w-full rounded-lg border border-slate-200 p-3 text-left text-sm hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
                >
                  <div className="font-medium text-slate-900 dark:text-slate-50">
                    Concept check question
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    Slots: 2 MCQ + 1 fill-in per concept. Fill-in blank uses exactly 5
                    underscores: <span className="font-mono font-semibold">_____</span>.{" "}
                    {mcqFull && fillFull
                      ? "All slots full."
                      : `${(cc?.mcq_cap ?? 2) - (cc?.mcq_count ?? 0)} MCQ and ${(cc?.fill_in_blank_cap ?? 1) - (cc?.fill_in_blank_count ?? 0)} fill-in remaining.`}
                  </div>
                </button>
                <button
                  type="button"
                  disabled={busy || clusterFull}
                  onClick={() => selectStage("cluster_quiz")}
                  className="w-full rounded-lg border border-slate-200 p-3 text-left text-sm hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
                >
                  <div className="font-medium text-slate-900 dark:text-slate-50">
                    Cluster quiz question
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {clusterFull
                      ? "This cluster already has 3 cluster-quiz questions. Remove one from a previous concept first."
                      : `${cq?.remaining ?? 3} of ${cq?.cap ?? 3} cluster slots remaining (shared across concepts in this cluster). Descriptive or MCQ.`}
                  </div>
                </button>
              </div>
            ) : null}

            {modalStep === "form" && quizStage ? (
              <div className="space-y-2">
                {quizStage === "concept_check" ? (
                  <div className="flex flex-wrap gap-2 text-xs">
                    <button
                      type="button"
                      disabled={busy || (mcqFull && !editingQuestionId)}
                      onClick={() => setQuestionKind("mcq")}
                      className={`rounded-lg border px-2 py-1 ${
                        questionKind === "mcq"
                          ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                          : "border-slate-200 dark:border-slate-600"
                      } disabled:opacity-40`}
                    >
                      MCQ ({cc?.mcq_count ?? 0}/{cc?.mcq_cap ?? 2})
                    </button>
                    <button
                      type="button"
                      disabled={busy || (fillFull && !editingQuestionId)}
                      onClick={() => setQuestionKind("fill_blank")}
                      className={`rounded-lg border px-2 py-1 ${
                        questionKind === "fill_blank"
                          ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                          : "border-slate-200 dark:border-slate-600"
                      } disabled:opacity-40`}
                    >
                      Fill-in ({cc?.fill_in_blank_count ?? 0}/{cc?.fill_in_blank_cap ?? 1})
                    </button>
                  </div>
                ) : (
                  <select
                    value={questionKind === "fill_blank" ? "descriptive" : questionKind}
                    onChange={(e) => setQuestionKind(e.target.value as QuestionKind)}
                    disabled={busy}
                    className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-950"
                  >
                    <option value="descriptive">Descriptive</option>
                    <option value="mcq">MCQ</option>
                  </select>
                )}
                <textarea
                  ref={questionTextRef}
                  value={questionText}
                  onChange={(e) => {
                    setQuestionText(e.target.value);
                    questionCursorRef.current = {
                      start: e.target.selectionStart ?? e.target.value.length,
                      end: e.target.selectionEnd ?? e.target.value.length,
                    };
                  }}
                  onSelect={rememberQuestionCursor}
                  onKeyUp={rememberQuestionCursor}
                  onClick={rememberQuestionCursor}
                  onBlur={rememberQuestionCursor}
                  rows={3}
                  disabled={busy}
                  placeholder={
                    questionKind === "fill_blank"
                      ? "Example: Humans are _____."
                      : "Question text…"
                  }
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60 dark:border-slate-600 dark:bg-slate-950"
                />
                {questionKind === "fill_blank" ? (
                  <div className="rounded-lg border border-amber-200/80 bg-amber-50/80 px-3 py-2 text-xs text-amber-950 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-100">
                    <p className="font-medium">Fill-in format (required)</p>
                    <p className="mt-1">
                      Use exactly{" "}
                      <span className="font-semibold">5 underscores</span>:{" "}
                      <span className="rounded bg-white/80 px-1.5 py-0.5 font-mono text-[12px] font-bold tracking-widest dark:bg-black/30">
                        {FILL_BLANK_MARKER}
                      </span>{" "}
                      for the blank. Do not use dashes (-) or fewer underscores.
                    </p>
                    <p className="mt-1.5">
                      Place the cursor where the blank should go, then click Insert.
                    </p>
                    <p className="mt-1 font-mono text-[11px] opacity-90">
                      Correct: Humans are {FILL_BLANK_MARKER}. → answer: living
                    </p>
                    <button
                      type="button"
                      disabled={busy}
                      onMouseDown={(e) => {
                        // Keep textarea selection; don't steal focus before we read cursor.
                        e.preventDefault();
                      }}
                      onClick={insertBlankAtCursor}
                      className="mt-2 rounded-md border border-amber-300/80 bg-white px-2 py-1 text-[11px] font-medium text-amber-950 hover:bg-amber-100/80 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-50"
                    >
                      Insert {FILL_BLANK_MARKER} (5 underscores)
                    </button>
                  </div>
                ) : null}
                {questionKind === "mcq" ? (
                  <div className="space-y-2">
                    {mcqOptions.map((opt, idx) => (
                      <input
                        key={idx}
                        value={opt}
                        disabled={busy}
                        onChange={(e) => {
                          const next = [...mcqOptions];
                          next[idx] = e.target.value;
                          setMcqOptions(next);
                        }}
                        placeholder={`Option ${idx + 1}`}
                        className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-950"
                      />
                    ))}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setMcqOptions([...mcqOptions, ""])}
                      className="text-xs text-sky-700 dark:text-sky-300"
                    >
                      + Add option
                    </button>
                    <input
                      value={mcqCorrect}
                      disabled={busy}
                      onChange={(e) => setMcqCorrect(e.target.value)}
                      placeholder="Correct answer (exact option text)"
                      className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-950"
                    />
                  </div>
                ) : null}
                {questionKind === "fill_blank" ? (
                  <div className="space-y-1">
                    <input
                      value={fillAnswer}
                      disabled={busy}
                      onChange={(e) => setFillAnswer(e.target.value)}
                      placeholder="Correct word/phrase for the blank"
                      className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-950"
                    />
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">
                      Enter the missing word that replaces{" "}
                      <span className="font-mono font-semibold">{FILL_BLANK_MARKER}</span>{" "}
                      (exactly 5 underscores).
                    </p>
                  </div>
                ) : null}
                <textarea
                  value={questionExplanation}
                  onChange={(e) => setQuestionExplanation(e.target.value)}
                  rows={2}
                  disabled={busy}
                  placeholder="Explanation (optional)…"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60 dark:border-slate-600 dark:bg-slate-950"
                />
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void saveStructuredQuestion()}
                    className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                  >
                    {busy ? "Saving…" : editingQuestionId ? "Update question" : "Add question"}
                  </button>
                  {!editingQuestionId ? (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setModalStep("pick_stage")}
                      className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-600"
                    >
                      Back
                    </button>
                  ) : null}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={resetQuestionForm}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-600"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
