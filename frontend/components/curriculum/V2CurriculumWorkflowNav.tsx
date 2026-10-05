"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, CalendarDays, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

export type V2WorkflowNavActive = "builder" | "planning" | "learningFlow";

type V2CurriculumWorkflowNavProps = {
  topicName?: string;
  builderHref: string;
  planningHref?: string | null;
  workspaceHref?: string | null;
  active: V2WorkflowNavActive;
  className?: string;
};

export function V2CurriculumWorkflowNav({
  topicName,
  builderHref,
  planningHref,
  workspaceHref,
  active,
  className,
}: V2CurriculumWorkflowNavProps) {
  const pill = (
    id: V2WorkflowNavActive,
    label: string,
    icon: ReactNode | null,
    href: string | null | undefined,
    isActive: boolean
  ) => {
    const className = cn(
      "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition",
      isActive
        ? "bg-violet-700 text-white shadow-sm dark:bg-violet-600"
        : "bg-white text-violet-900 ring-1 ring-violet-200 hover:bg-violet-100 dark:bg-slate-900 dark:text-violet-100 dark:ring-violet-800 dark:hover:bg-violet-950/60"
    );

    if (isActive || !href) {
      return (
        <span className={className} aria-current={isActive ? "page" : undefined}>
          {icon}
          {label}
        </span>
      );
    }

    return (
      <Link href={href} className={className}>
        {icon}
        {label}
      </Link>
    );
  };

  return (
    <nav
      aria-label="Structured curriculum workflow"
      className={cn(
        "rounded-xl border border-violet-200/80 bg-violet-50/60 p-3 dark:border-violet-900/50 dark:bg-violet-950/25",
        className
      )}
    >
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-violet-800 dark:text-violet-200">
          Structured curriculum (v2)
        </p>
        {topicName ? (
          <p className="truncate text-xs text-violet-700/90 dark:text-violet-300/90">
            {topicName}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {workspaceHref && active !== "learningFlow"
          ? pill(
              "learningFlow",
              "Workspace",
              <ArrowLeft className="size-4 shrink-0 opacity-90" />,
              workspaceHref,
              false
            )
          : null}
        {pill(
          "builder",
          "Structured curriculum",
          <BookOpen className="size-4 shrink-0 opacity-90" />,
          builderHref,
          active === "builder"
        )}
        {planningHref
          ? pill(
              "planning",
              "Session planning",
              <CalendarDays className="size-4 shrink-0 opacity-90" />,
              planningHref,
              active === "planning"
            )
          : null}
        {pill(
          "learningFlow",
          "Learning flow",
          <GitBranch className="size-4 shrink-0 opacity-90" />,
          workspaceHref,
          active === "learningFlow"
        )}
      </div>
    </nav>
  );
}
