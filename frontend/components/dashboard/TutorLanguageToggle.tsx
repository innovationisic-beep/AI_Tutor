"use client";

import { useCallback, useEffect, useState, useTransition } from "react";
import { getStudentProfile, updateStudentProfile } from "@/lib/api";
import type { TutorLanguage } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const OPTIONS: { value: TutorLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hinglish", label: "Hinglish" },
];

export function TutorLanguageToggle({ token }: { token: string | null }) {
  const [language, setLanguage] = useState<TutorLanguage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    if (!token) return;
    let active = true;
    void getStudentProfile(token)
      .then((p) => {
        if (active) setLanguage(p.preferred_language ?? "en");
      })
      .catch(() => {
        if (active) setLanguage("en");
      });
    return () => {
      active = false;
    };
  }, [token]);

  const select = useCallback(
    (next: TutorLanguage) => {
      if (!token || next === language) return;
      const previous = language;
      setLanguage(next);
      setError(null);
      startTransition(async () => {
        try {
          const saved = await updateStudentProfile(token, {
            preferred_language: next,
          });
          setLanguage(saved.preferred_language ?? next);
        } catch {
          setLanguage(previous);
          setError("Could not save your language. Try again.");
        }
      });
    },
    [language, token]
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium text-slate-600 dark:text-slate-400">
          Tutor language
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          role="radiogroup"
          aria-label="Tutor language"
          className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-900"
        >
          {OPTIONS.map((opt) => {
            const selected = language === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={!token || pending}
                onClick={() => select(opt.value)}
                className={cn(
                  "rounded-md px-4 py-1.5 text-sm font-medium transition disabled:opacity-60",
                  selected
                    ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-50"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                )}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Hinglish applies to conversational parts of the lesson. Quizzes and
          formal explanations stay in English. Takes effect from the next tutor
          response — no need to restart a session.
        </p>
        {error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
