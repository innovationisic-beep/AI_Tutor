"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  getCurriculumCatalogSubjects,
  linkOrgSubjectToCurriculum,
  type CurriculumSubjectCatalogItem,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type CurriculumSubjectLinkModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string | null;
  classId: string;
  subjectId: string;
  /** Org subject display name (for exact-match auto-suggest) */
  orgSubjectName: string;
  /** When set, dropdown preselects this curriculum subject id */
  initialCurriculumSubjectId?: string | null;
  onLinked: () => void;
  onToast: (message: string, variant?: "ok" | "err") => void;
};

export function CurriculumSubjectLinkModal({
  open,
  onOpenChange,
  token,
  classId,
  subjectId,
  orgSubjectName,
  initialCurriculumSubjectId,
  onLinked,
  onToast,
}: CurriculumSubjectLinkModalProps) {
  const [catalog, setCatalog] = useState<CurriculumSubjectCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [pick, setPick] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const exactMatch =
    catalog.find((c) => c.name === orgSubjectName.trim()) ?? null;

  useEffect(() => {
    if (!open || !token) {
      if (!open) {
        setCatalog([]);
        setPick("");
        setError(null);
      }
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const list = await getCurriculumCatalogSubjects(token);
        if (cancelled) return;
        setCatalog(list);
        const init = initialCurriculumSubjectId?.trim();
        const byName = list.find((c) => c.name === orgSubjectName.trim());
        let next = "";
        if (init && list.some((x) => x.id === init)) next = init;
        else if (byName) next = byName.id;
        else next = list[0]?.id ?? "";
        setPick(next);
      } catch (e) {
        if (!cancelled) {
          setCatalog([]);
          setError(e instanceof Error ? e.message : "Failed to load subjects");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, token, classId, subjectId, initialCurriculumSubjectId, orgSubjectName]);

  async function submitLink(curriculumId: string | null) {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      await linkOrgSubjectToCurriculum(token, classId, subjectId, curriculumId);
      onToast(
        curriculumId ? "Subject linked successfully" : "Link removed",
        "ok"
      );
      onLinked();
      onOpenChange(false);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Request failed", "err");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px]"
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="curriculum-link-title"
        className={cn(
          "relative z-10 w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-lg",
          "dark:border-slate-700 dark:bg-slate-900"
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <h2
            id="curriculum-link-title"
            className="text-lg font-semibold text-slate-900 dark:text-slate-50"
          >
            Link to curriculum subject
          </h2          >
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="Close"
          >
            <X className="size-5" />
          </button>
        </div>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
          Org subject:{" "}
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {orgSubjectName}
          </span>
        </p>

        {exactMatch ? (
          <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-violet-200 bg-violet-50/80 px-3 py-2 text-sm dark:border-violet-900/50 dark:bg-violet-950/30">
            <span className="text-slate-700 dark:text-slate-300">
              Suggested:{" "}
              <span className="font-medium text-violet-900 dark:text-violet-100">
                {exactMatch.name}
              </span>
            </span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={submitting || !token}
              onClick={() => void submitLink(exactMatch.id)}
              className="shrink-0"
            >
              Auto link
            </Button>
          </div>
        ) : null}

        {loading ? (
          <p className="text-sm text-slate-500">Loading curriculum subjects…</p>
        ) : error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : catalog.length === 0 ? (
          <p className="text-sm text-slate-500">
            No active curriculum subjects in your organization. Create subjects in
            curriculum admin first.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="curriculum-pick">Select curriculum subject</Label>
              <select
                id="curriculum-pick"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
              >
                {catalog.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={submitting || !pick || !token}
                onClick={() => void submitLink(pick)}
              >
                {submitting ? "Linking…" : "Link"}
              </Button>
              {initialCurriculumSubjectId ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={submitting || !token}
                  onClick={() => void submitLink(null)}
                  className="text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                >
                  Remove link
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={submitting}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
