"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Mic, Send } from "lucide-react";
import { useSpeechToText } from "@/lib/useSpeechToText";
import { cn } from "@/lib/utils";
import { CHAT_INPUT_TEXT_CLASS, CHAT_META_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Shown under the field when the input is disabled (e.g. teacher flow). */
  disabledHint?: string | null;
  /** Tighter chrome when mounted under the whiteboard. */
  compact?: boolean;
};

function isThinkingHint(hint: string | null | undefined): boolean {
  if (!hint) return false;
  const t = hint.trim().toLowerCase();
  return t === "thinking…" || t === "thinking...";
}

export function InputBox({
  onSend,
  disabled,
  placeholder,
  disabledHint,
  compact = false,
}: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const { isListening, startListening, stopListening } = useSpeechToText();

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

  function submit() {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  }

  const thinkingInline = Boolean(disabled && isThinkingHint(disabledHint));

  return (
    <div
      className={cn(
        compact
          ? "border-0 bg-transparent p-2.5 md:p-3"
          : "border-t border-slate-200/80 bg-white/95 p-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95"
      )}
      data-testid="board-composer"
    >
      <div className="mx-auto max-w-3xl space-y-2">
        <div className="flex items-center gap-2">
          {thinkingInline ? (
            <span
              className={cn(
                "shrink-0 text-slate-500 dark:text-slate-400",
                CHAT_META_TEXT_CLASS
              )}
              data-testid="composer-thinking"
              aria-live="polite"
            >
              Thinking…
            </span>
          ) : null}
          <Input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={placeholder ?? "Message your tutor…"}
            disabled={disabled}
            className={cn("min-w-0 flex-1", CHAT_INPUT_TEXT_CLASS)}
            aria-busy={isListening || thinkingInline}
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
          <Button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            aria-label="Send"
          >
            <Send className="size-4" />
          </Button>
        </div>
        {isListening && !disabled ? (
          <p className={`text-red-600 dark:text-red-400 ${CHAT_META_TEXT_CLASS}`}>
            Listening… speak now.
          </p>
        ) : null}
        {disabled && disabledHint && !thinkingInline ? (
          <p className={`text-slate-500 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
            {disabledHint}
          </p>
        ) : null}
      </div>
    </div>
  );
}
