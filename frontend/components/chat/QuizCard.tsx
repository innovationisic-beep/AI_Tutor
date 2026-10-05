"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MessageBubble } from "./MessageBubble";
import { CHAT_INPUT_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

type Props = {
  intro: string;
  question: string;
  disabled?: boolean;
  onSubmit: (answer: string) => void;
};

export function QuizCard({
  intro,
  question,
  disabled,
  onSubmit,
}: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
    setValue("");
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {intro ? (
        <MessageBubble role="assistant">
          <p className="whitespace-pre-wrap">{intro}</p>
        </MessageBubble>
      ) : null}
      <Card className="max-w-[min(100%,42rem)] border-amber-200/80 bg-amber-50/50 dark:border-amber-900/50 dark:bg-amber-950/20">
        <CardHeader className="pb-2">
          <CardTitle className={`text-amber-950 dark:text-amber-100 ${CHAT_TEXT_CLASS}`}>
            Quick check
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className={`whitespace-pre-wrap text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
            {question}
          </p>
          <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Your answer"
              disabled={disabled}
              className={cn("flex-1", CHAT_INPUT_TEXT_CLASS)}
            />
            <Button type="submit" disabled={disabled || !value.trim()}>
              Submit
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
