"use client";

import { parseTeachingContent } from "./parseTeachingContent";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

type TeachingBlockProps = {
  text: string;
};

const proseClass = cn(WHITEBOARD_TEXT_CLASS, "whitespace-pre-wrap");

export function TeachingBlock({ text }: TeachingBlockProps) {
  const parsed = parseTeachingContent(text);
  const hasStructure =
    Boolean(parsed.intro) ||
    parsed.bullets.length > 0 ||
    Boolean(parsed.example) ||
    Boolean(parsed.summary);

  if (text.trim() && !hasStructure) {
    const plain = text.replace(/\*\*/g, "").replace(/\*/g, "");
    return <p className={proseClass}>{plain}</p>;
  }

  return (
    <div className={cn("space-y-4", WHITEBOARD_TEXT_CLASS)}>
      {parsed.intro ? <p className={proseClass}>{parsed.intro}</p> : null}

      {parsed.bullets.length > 0 ? (
        <ul className="list-disc space-y-2 pl-4">
          {parsed.bullets.map((b, i) => (
            <li key={i} className={proseClass}>
              {b}
            </li>
          ))}
        </ul>
      ) : null}

      {parsed.example ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800/80 dark:bg-blue-950/35">
          <p className={cn(WHITEBOARD_TEXT_CLASS, "font-medium text-blue-700 dark:text-blue-300")}>
            Example
          </p>
          <p className={cn(proseClass, "mt-1 text-blue-800 dark:text-blue-100/90")}>
            {parsed.example}
          </p>
        </div>
      ) : null}

      {parsed.summary ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-800/80 dark:bg-emerald-950/35">
          <p className={cn(WHITEBOARD_TEXT_CLASS, "font-medium text-emerald-700 dark:text-emerald-300")}>
            Quick Summary
          </p>
          <p className={cn(proseClass, "mt-1 text-emerald-800 dark:text-emerald-100/90")}>
            {parsed.summary}
          </p>
        </div>
      ) : null}
    </div>
  );
}
