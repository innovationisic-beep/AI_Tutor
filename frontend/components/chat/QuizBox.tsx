"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Lightbulb, Mic } from "lucide-react";
import { useSpeechToText } from "@/lib/useSpeechToText";
import { cn } from "@/lib/utils";
import { CHAT_INPUT_TEXT_CLASS, CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  intro: string;
  question: string;
  disabled?: boolean;
  currentZone?: number;
  onSubmit: (answer: string) => void;
};

/**
 * Standalone quiz panel below chat (answer field + submit).
 */
export function QuizBox({
  intro,
  question,
  disabled,
  currentZone,
  onSubmit,
}: Props) {
  const [value, setValue] = useState("");
  const [hintLoading, setHintLoading] = useState(false);
  const [hintsUsed, setHintsUsed] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { isListening, startListening, stopListening } = useSpeechToText();
  const isZone3 = currentZone === 3;
  const MAX_HINTS = 2;
  const hintsRemaining = MAX_HINTS - hintsUsed;

  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  function handleMicClick() {
    if (disabled) return;
    if (isListening) {
      stopListening();
      return;
    }
    startListening((text) => {
      setValue((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
    });
  }

  function handleHint() {
    if (disabled || hintLoading || hintsRemaining <= 0) return;
    setHintLoading(true);
    setHintsUsed((n) => n + 1);
    onSubmit("hint");
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
    setValue("");
  }

  // When the intro changes, the hint response has arrived — stop the spinner.
  useEffect(() => {
    setHintLoading(false);
  }, [intro]);

  // When the question itself changes (new quiz question), reset the full hint state.
  useEffect(() => {
    setHintLoading(false);
    setHintsUsed(0);
  }, [question]);

  return (
    <div className="shrink-0 border-t border-amber-200/80 bg-amber-50/40 px-4 py-4 dark:border-amber-900/40 dark:bg-amber-950/15">
      <div className="mx-auto max-w-3xl">
        <Card className="rounded-2xl border-amber-200/80 bg-white/90 shadow-sm dark:border-amber-900/50 dark:bg-slate-900/80">
          <CardHeader className="space-y-1 pb-2">
            <CardTitle className={`text-amber-950 dark:text-amber-100 ${CHAT_TEXT_CLASS}`}>
              Quick check
            </CardTitle>
            {intro ? (
              <p className={`text-slate-600 dark:text-slate-300 ${CHAT_TEXT_CLASS}`}>
                {intro}
              </p>
            ) : null}
          </CardHeader>
          <CardContent className="space-y-3">
            <p className={`whitespace-pre-wrap text-slate-900 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
              {question}
            </p>
            <form
              onSubmit={handleSubmit}
              className="flex flex-col gap-2 sm:flex-row sm:items-end"
            >
              <div className="flex w-full flex-1 gap-2 sm:min-w-0">
                <Input
                  ref={inputRef}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="Type or speak your answer…"
                  disabled={disabled}
                  className={cn("min-w-0 flex-1", CHAT_INPUT_TEXT_CLASS)}
                  aria-label="Quiz answer"
                  aria-busy={isListening}
                />
                <Button
                  type="button"
                  variant={isListening ? "destructive" : "outline"}
                  onClick={handleMicClick}
                  disabled={disabled}
                  aria-label={isListening ? "Stop voice input" : "Voice input"}
                  aria-pressed={isListening}
                  className={cn(
                    "shrink-0",
                    isListening && "animate-pulse"
                  )}
                >
                  <Mic className="size-4" />
                </Button>
              </div>
              <Button
                type="submit"
                disabled={disabled || !value.trim()}
                className="rounded-2xl shadow-sm transition-transform hover:scale-[1.01] active:scale-[0.99]"
              >
                Submit answer
              </Button>
            </form>
            {isListening && !disabled ? (
              <p className={`text-red-600 dark:text-red-400 ${CHAT_META_TEXT_CLASS}`}>
                Listening… speak your answer.
              </p>
            ) : null}
            {isZone3 ? (
              <div className="flex items-center gap-2 pt-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleHint}
                  disabled={disabled || hintLoading || hintsRemaining <= 0}
                  className={cn(
                    "h-7 gap-1.5 rounded-full border border-amber-300/60 px-3 text-xs",
                    "text-amber-700 hover:bg-amber-50 hover:text-amber-800",
                    "dark:border-amber-700/40 dark:text-amber-400 dark:hover:bg-amber-950/40",
                    (hintLoading || hintsRemaining <= 0) && "opacity-50 cursor-not-allowed"
                  )}
                >
                  <Lightbulb className="size-3.5" />
                  {hintsRemaining <= 0
                    ? "No hints left"
                    : hintLoading
                    ? "Getting hint…"
                    : `Get a hint (${hintsRemaining} left)`}
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
