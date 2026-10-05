"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Mic } from "lucide-react";
import { useSpeechToText } from "@/lib/useSpeechToText";
import { cn } from "@/lib/utils";
import { CHAT_INPUT_TEXT_CLASS, CHAT_META_TEXT_CLASS } from "@/lib/teachingTypography";

type Props = {
  onSend: (text: string) => void;
  disabled?: boolean;
};

export function TeachbackInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { isListening, startListening, stopListening } = useSpeechToText();

  useEffect(() => {
    if (!disabled) textareaRef.current?.focus();
  }, [disabled]);

  function submit() {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  }

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

  return (
    <div className="border-t border-indigo-200/80 bg-indigo-50/60 px-4 py-4 dark:border-indigo-900/60 dark:bg-indigo-950/20">
      <div className="mx-auto max-w-3xl space-y-3">
        <p className={`uppercase tracking-wide text-indigo-700/80 dark:text-indigo-300/80 ${CHAT_META_TEXT_CLASS}`}>
          Teachback — explain in your own words
        </p>
        <div className="relative">
          <textarea
            ref={textareaRef}
            rows={4}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={disabled}
            placeholder="Explain this concept in your own words as if teaching someone."
            className={cn(
              "w-full resize-none rounded-xl border px-4 py-3 pr-12",
              CHAT_INPUT_TEXT_CLASS,
              "border-indigo-200 bg-white placeholder:text-slate-400 focus:outline-none",
              "focus:ring-2 focus:ring-indigo-400/60 focus:border-indigo-400",
              "dark:border-indigo-800 dark:bg-slate-900 dark:text-slate-100",
              "dark:placeholder:text-slate-500 dark:focus:ring-indigo-500/40",
              "disabled:cursor-not-allowed disabled:opacity-50",
              "transition-shadow"
            )}
          />
          <Button
            type="button"
            variant={isListening ? "destructive" : "ghost"}
            size="icon"
            onClick={handleMicClick}
            disabled={disabled}
            aria-label={isListening ? "Stop voice input" : "Voice input"}
            aria-pressed={isListening}
            className={cn(
              "absolute right-2 top-2 size-8 rounded-lg",
              isListening && "animate-pulse"
            )}
          >
            <Mic className="size-4" />
          </Button>
        </div>
        {isListening && !disabled && (
          <p className={`text-red-600 dark:text-red-400 ${CHAT_META_TEXT_CLASS}`}>
            Listening… speak your explanation.
          </p>
        )}
        <div className="flex items-center justify-between">
          <p className={`text-indigo-600/70 dark:text-indigo-400/70 ${CHAT_META_TEXT_CLASS}`}>
            Ctrl + Enter to submit
          </p>
          <Button
            type="button"
            disabled={disabled || !value.trim()}
            onClick={submit}
            className={cn(
              "rounded-xl bg-indigo-600 px-5 py-2 text-white",
              CHAT_META_TEXT_CLASS,
              "hover:bg-indigo-700 active:bg-indigo-800",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "transition-colors"
            )}
          >
            Check my explanation
          </Button>
        </div>
      </div>
    </div>
  );
}
