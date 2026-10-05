"use client";

import type { PlanProgressionView } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  progression: PlanProgressionView | null;
  /** Header chip (default) or legacy full-width banner. */
  variant?: "compact" | "banner";
  className?: string;
};

function pathIcon(state: string) {
  if (state === "completed") return "✓";
  if (state === "active") return "▶";
  return "○";
}

function pathLabel(state: string) {
  if (state === "completed") return "Completed";
  if (state === "active") return "Active";
  if (state === "available") return "Available";
  return "Locked";
}

function transitionHint(progression: PlanProgressionView): string | null {
  const transition =
    progression.last_transition ?? progression.transition?.unlock ?? null;
  const title =
    (transition && "title" in transition ? transition.title : null) ??
    progression.transition?.unlock?.title ??
    null;
  const subtitle =
    (transition && "subtitle" in transition ? transition.subtitle : null) ??
    progression.transition?.unlock?.subtitle ??
    null;
  if (title && subtitle) return `${title} — ${subtitle}`;
  return title ?? subtitle ?? null;
}

/** Compact session path for the top bar; full banner kept for optional QA use. */
export function SessionProgressionIndicator({
  progression,
  variant = "compact",
  className,
}: Props) {
  if (!progression) return null;

  const path = progression.learning_path ?? [];
  const hint = transitionHint(progression);
  if (path.length === 0 && !hint) return null;

  if (variant === "compact") {
    if (path.length === 0) return null;
    return (
      <div
        className={cn(
          "flex max-w-[min(220px,42vw)] shrink-0 items-center gap-0.5 overflow-hidden rounded border border-amber-300/70 bg-amber-50/90 px-1.5 py-0.5 text-[10px] font-medium leading-none text-amber-950 dark:border-amber-700/50 dark:bg-amber-950/40 dark:text-amber-100",
          className
        )}
        data-testid="session-progression-banner"
        title={hint ?? "Learning path"}
      >
        {path.map((row, i) => (
          <span
            key={row.session_plan_id}
            className={cn(
              "inline-flex shrink-0 items-center gap-px whitespace-nowrap",
              row.state === "active" && "font-bold text-amber-800 dark:text-amber-200"
            )}
            title={`Session ${row.sequence_number}${row.title ? `: ${row.title}` : ""} (${pathLabel(row.state)})`}
          >
            {i > 0 ? (
              <span className="mx-0.5 text-amber-400 dark:text-amber-600">·</span>
            ) : null}
            <span aria-hidden>{pathIcon(row.state)}</span>
            <span>S{row.sequence_number}</span>
          </span>
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "mb-4 rounded-lg border-2 border-amber-400 bg-amber-50 px-4 py-3 text-amber-950 shadow-sm",
        className
      )}
      data-testid="session-progression-banner"
    >
      {hint ? (
        <div className="mb-2">
          <p className="text-lg font-bold tracking-wide">{hint.split(" — ")[0]}</p>
          {hint.includes(" — ") ? (
            <p className="text-sm font-medium text-amber-900">
              {hint.split(" — ").slice(1).join(" — ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {path.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-amber-800">
            Current Learning Path
          </p>
          <ul className="space-y-1 text-sm">
            {path.map((row) => (
              <li key={row.session_plan_id} className="flex items-center gap-2">
                <span className="w-4 text-center font-bold">
                  {pathIcon(row.state)}
                </span>
                <span>
                  Session {row.sequence_number}
                  {row.title ? ` — ${row.title}` : ""}{" "}
                  <span className="text-amber-800">({pathLabel(row.state)})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** @deprecated Use SessionProgressionIndicator in the header. */
export function SessionProgressionBanner(props: Props) {
  return <SessionProgressionIndicator {...props} variant="banner" />;
}
