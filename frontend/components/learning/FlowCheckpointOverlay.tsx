"use client";

import { useEffect, useState } from "react";
import { Mic } from "lucide-react";

import type { FlowCheckpointEvent } from "@/lib/learning/flowCheckpointOrchestrator";
import {
  splitClarificationText,
  type FlowCheckpointUiPhase,
} from "@/lib/learning/useFlowCheckpointController";
import { useSpeechToText } from "@/lib/useSpeechToText";
import { cn } from "@/lib/utils";

type Props = {
  phase: FlowCheckpointUiPhase;
  event: FlowCheckpointEvent | null;
  clarification: string | null;
  continuing?: boolean;
  continueError?: string | null;
  onContinue: () => void;
  onAskQuestion: () => void;
  onAskAnotherQuestion: () => void;
  onSubmitQuestion: (text: string) => void;
  onDismissAfterClarification: () => void;
};

export function FlowCheckpointOverlay({
  phase,
  event,
  clarification,
  continuing = false,
  continueError = null,
  onContinue,
  onAskQuestion,
  onAskAnotherQuestion,
  onSubmitQuestion,
  onDismissAfterClarification,
}: Props) {
  const [draft, setDraft] = useState("");
  const { isListening, startListening, stopListening } = useSpeechToText();

  useEffect(() => {
    if (phase === "question_input") {
      setDraft("");
    } else {
      stopListening();
    }
  }, [phase, stopListening]);

  useEffect(() => {
    return () => {
      stopListening();
    };
  }, [stopListening]);

  function handleMicClick() {
    if (phase !== "question_input" || continuing) return;
    if (isListening) {
      stopListening();
      return;
    }
    startListening((text) => {
      setDraft((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
    });
  }

  function handleSubmitQuestion() {
    const q = draft.trim();
    if (!q || continuing) return;
    stopListening();
    onSubmitQuestion(q);
  }

  if (phase === "idle" || !event) return null;

  const showQuestionInput = phase === "question_input";
  const showClarifying = phase === "clarifying";
  const showClarification = phase === "clarification_done" && clarification;
  const { body: clarificationBody, closing: clarificationClosing } = showClarification
    ? splitClarificationText(clarification)
    : { body: "", closing: null };

  return (
    <div
      className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center p-4"
      data-testid="flow-checkpoint-overlay"
      aria-live="polite"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="flow-checkpoint-title"
        aria-busy={continuing}
        className="pointer-events-auto w-full max-w-md rounded-2xl border border-slate-200/80 bg-white/95 p-6 shadow-[0_24px_64px_-12px_rgba(15,23,42,0.28)] backdrop-blur-md dark:border-slate-600/60 dark:bg-slate-900/95 dark:shadow-[0_28px_70px_-14px_rgba(0,0,0,0.65)]"
      >
        <p
          id="flow-checkpoint-title"
          className="text-xs font-semibold uppercase tracking-[0.14em] text-indigo-600 dark:text-indigo-300"
        >
          {showClarification ? "Clarification" : "Quick Checkpoint"}
        </p>

        {!showClarification && !showClarifying ? (
          <>
            <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
              You have completed:
            </p>
            <ul className="mt-2 space-y-1.5">
              {event.stepLabels.map((label) => (
                <li
                  key={label}
                  className="flex items-start gap-2 text-sm text-slate-800 dark:text-slate-100"
                >
                  <span className="mt-0.5 text-indigo-500" aria-hidden>
                    •
                  </span>
                  <span>{label}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
              Would you like clarification before we continue?
            </p>
          </>
        ) : null}

        {showClarifying ? (
          <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
            Preparing a focused clarification…
          </p>
        ) : null}

        {showClarification ? (
          <div className="mt-3 space-y-3">
            {clarificationBody ? (
              <p
                className="text-sm leading-relaxed text-slate-800 dark:text-slate-100"
                data-testid="flow-checkpoint-clarification-body"
              >
                {clarificationBody}
              </p>
            ) : null}
            {clarificationClosing ? (
              <p
                className="text-sm font-medium text-slate-600 dark:text-slate-400"
                data-testid="flow-checkpoint-clarification-closing"
              >
                {clarificationClosing}
              </p>
            ) : null}
          </div>
        ) : null}

        {showQuestionInput ? (
          <div className="mt-4">
            <label htmlFor="flow-checkpoint-question" className="sr-only">
              Your question
            </label>
            <div className="flex gap-2">
              <textarea
                id="flow-checkpoint-question"
                rows={3}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Type or speak your question…"
                aria-busy={isListening}
                disabled={continuing}
                className="min-w-0 flex-1 resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-inner focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-indigo-500 dark:focus:ring-indigo-900"
              />
              <button
                type="button"
                onClick={handleMicClick}
                disabled={continuing}
                aria-label={isListening ? "Stop voice input" : "Voice input"}
                aria-pressed={isListening}
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center self-start rounded-lg border transition",
                  isListening
                    ? "animate-pulse border-red-300 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-950/40 dark:text-red-400"
                    : "border-slate-200 text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800",
                  continuing && "cursor-not-allowed opacity-50",
                )}
              >
                <Mic className="size-4" />
              </button>
            </div>
            {isListening ? (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400">
                Listening… speak your question.
              </p>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleSubmitQuestion}
                disabled={!draft.trim() || continuing}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Send question
              </button>
              <button
                type="button"
                onClick={() => {
                  stopListening();
                  onContinue();
                }}
                disabled={continuing}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                {continuing ? "Continuing…" : "Skip — continue"}
              </button>
            </div>
          </div>
        ) : null}

        {continuing ? (
          <p
            className="mt-4 text-sm text-slate-600 dark:text-slate-400"
            data-testid="flow-checkpoint-continuing"
          >
            Clearing checkpoint…
          </p>
        ) : null}

        {continueError && !continuing ? (
          <p
            className="mt-4 text-sm text-red-600 dark:text-red-400"
            data-testid="flow-checkpoint-continue-error"
            role="alert"
          >
            {continueError}
          </p>
        ) : null}

        {!showQuestionInput && !showClarifying ? (
          <div className="mt-5 flex flex-wrap gap-2">
            {showClarification ? (
              <>
                <button
                  type="button"
                  onClick={onAskAnotherQuestion}
                  disabled={continuing}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  Ask another question
                </button>
                <button
                  type="button"
                  onClick={onDismissAfterClarification}
                  disabled={continuing}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {continuing ? "Continuing…" : "Continue"}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={onContinue}
                  disabled={continuing}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {continuing ? "Continuing…" : continueError ? "Retry Continue" : "Continue"}
                </button>
                <button
                  type="button"
                  onClick={onAskQuestion}
                  disabled={continuing}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  I Have A Question
                </button>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
