"use client";

import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

export type PedagogyIntroCardData = {
  kind: "session" | "cluster";
  heading: string;
  title: string;
  description?: string;
  study_points?: string[];
  learning_outcomes?: string[];
};

type PedagogyIntroCardProps = {
  card: PedagogyIntroCardData;
};

function cardHeadingFromPayload(c: Record<string, unknown>): string {
  if (typeof c.heading === "string" && c.heading.trim()) {
    return c.heading.trim();
  }
  if (typeof c.subtitle === "string" && c.subtitle.trim()) {
    return c.subtitle.trim();
  }
  return c.kind === "cluster" ? "CLUSTER" : "SESSION";
}

export function parsePedagogyIntroCard(
  visual: unknown
): PedagogyIntroCardData | null {
  if (!visual || typeof visual !== "object") return null;
  const v = visual as Record<string, unknown>;
  if (v.type !== "pedagogy_intro") return null;
  const card = v.card;
  if (!card || typeof card !== "object") return null;
  const c = card as Record<string, unknown>;
  const kind = c.kind === "cluster" ? "cluster" : "session";
  const title = typeof c.title === "string" ? c.title.trim() : "";
  const heading = cardHeadingFromPayload(c);
  if (!title && !heading) return null;
  return {
    kind,
    heading,
    title: title || heading,
    description: typeof c.description === "string" ? c.description : "",
    study_points: Array.isArray(c.study_points)
      ? c.study_points.map(String).filter(Boolean)
      : [],
    learning_outcomes: Array.isArray(c.learning_outcomes)
      ? c.learning_outcomes.map(String).filter(Boolean)
      : [],
  };
}

export function PedagogyIntroCard({ card }: PedagogyIntroCardProps) {
  const accent =
    card.kind === "session"
      ? "border-indigo-300 bg-gradient-to-br from-indigo-50 via-white to-violet-50 dark:border-indigo-800 dark:from-indigo-950/50 dark:via-slate-900 dark:to-violet-950/30"
      : "border-emerald-300 bg-gradient-to-br from-emerald-50 via-white to-teal-50 dark:border-emerald-800 dark:from-emerald-950/50 dark:via-slate-900 dark:to-teal-950/30";

  return (
    <article
      className={cn(
        "mx-auto max-w-2xl rounded-2xl border-2 p-6 shadow-md md:p-8",
        accent
      )}
      aria-label={`${card.heading}: ${card.title}`}
    >
      <header className="border-b border-slate-200/80 pb-4 text-center dark:border-slate-700">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          {card.heading}
        </p>
        <h3
          className={cn(
            WHITEBOARD_TEXT_CLASS,
            "mt-2 text-2xl font-bold text-slate-900 md:text-3xl dark:text-slate-50"
          )}
        >
          {card.title}
        </h3>
        {card.description ? (
          <p
            className={cn(
              WHITEBOARD_TEXT_CLASS,
              "mt-3 text-slate-600 dark:text-slate-300"
            )}
          >
            {card.description}
          </p>
        ) : null}
      </header>

      {card.study_points && card.study_points.length > 0 ? (
        <section className="mt-6">
          <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            What We Will Study
          </h4>
          <ul className="mt-3 space-y-2">
            {card.study_points.map((point, i) => (
              <li
                key={i}
                className={cn(
                  WHITEBOARD_TEXT_CLASS,
                  "flex gap-3 rounded-lg bg-white/70 px-3 py-2 text-slate-800 dark:bg-slate-900/50 dark:text-slate-100"
                )}
              >
                <span
                  className="font-bold text-indigo-600 dark:text-indigo-400"
                  aria-hidden
                >
                  •
                </span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {card.learning_outcomes && card.learning_outcomes.length > 0 ? (
        <section className="mt-6">
          <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Learning Outcomes
          </h4>
          <ul className="mt-3 space-y-2">
            {card.learning_outcomes.map((point, i) => (
              <li
                key={i}
                className={cn(
                  WHITEBOARD_TEXT_CLASS,
                  "flex gap-3 rounded-lg bg-white/70 px-3 py-2 text-slate-800 dark:bg-slate-900/50 dark:text-slate-100"
                )}
              >
                <span
                  className="font-bold text-emerald-600 dark:text-emerald-400"
                  aria-hidden
                >
                  •
                </span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
