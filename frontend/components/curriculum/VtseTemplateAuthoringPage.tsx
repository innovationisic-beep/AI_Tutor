"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getCurriculumConcept,
  updateCurriculumConcept,
} from "@/lib/api/curriculumStructure";
import type {
  ConceptVtseTemplate,
  CurriculumTopicSource,
  VtseStrategyId,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STRATEGIES: Array<{
  id: VtseStrategyId;
  label: string;
  blurb: string;
}> = [
  {
    id: "comparison_contrast",
    label: "Comparison",
    blurb: "Two sides with paired points (left vs right).",
  },
  {
    id: "linear_process",
    label: "Linear process",
    blurb: "Ordered steps from start to finish.",
  },
  {
    id: "cycle_process",
    label: "Cycle",
    blurb: "Repeating stages that loop back.",
  },
  {
    id: "clustered_trait_list",
    label: "Trait list",
    blurb: "Cluster of traits under the concept.",
  },
  {
    id: "hierarchy_concept_intro",
    label: "Hierarchy",
    blurb: "Root concept with child nodes.",
  },
];

type ComparisonRowDraft = {
  dimension: string;
  left: string;
  right: string;
};

type StepDraft = {
  label: string;
  summary: string;
};

function emptyComparison(): { left_label: string; right_label: string; rows: ComparisonRowDraft[] } {
  return {
    left_label: "",
    right_label: "",
    rows: [
      { dimension: "", left: "", right: "" },
      { dimension: "", left: "", right: "" },
    ],
  };
}

function emptySteps(n = 3): StepDraft[] {
  return Array.from({ length: n }, () => ({ label: "", summary: "" }));
}

function parseInitial(
  tmpl: ConceptVtseTemplate | null | undefined
): {
  strategyId: VtseStrategyId | null;
  comparison: ReturnType<typeof emptyComparison>;
  steps: StepDraft[];
} {
  if (!tmpl?.strategy_id) {
    return { strategyId: null, comparison: emptyComparison(), steps: emptySteps() };
  }
  const payload = tmpl.payload || {};
  if (tmpl.strategy_id === "comparison_contrast") {
    const rows = (payload.rows || []).map((r) => ({
      dimension: r.dimension || "",
      left: r.left || r.left_detail || "",
      right: r.right || r.right_detail || "",
    }));
    return {
      strategyId: tmpl.strategy_id,
      comparison: {
        left_label: payload.left_label || "",
        right_label: payload.right_label || "",
        rows: rows.length >= 2 ? rows : emptyComparison().rows,
      },
      steps: emptySteps(),
    };
  }
  const steps = (payload.steps || []).map((s) => ({
    label: s.label || s.title || "",
    summary: s.summary || s.annotation || "",
  }));
  return {
    strategyId: tmpl.strategy_id,
    comparison: emptyComparison(),
    steps: steps.length >= 3 ? steps : emptySteps(),
  };
}

export function VtseTemplateAuthoringPage({
  conceptId,
  topicSource,
  token,
  backHref,
  mode = "page",
  onClose,
  onSaved,
}: {
  conceptId: string;
  topicSource: CurriculumTopicSource;
  token: string;
  backHref?: string;
  mode?: "page" | "modal";
  onClose?: () => void;
  onSaved?: () => void | Promise<void>;
}) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [strategyId, setStrategyId] = useState<VtseStrategyId | null>(null);
  const [comparison, setComparison] = useState(emptyComparison());
  const [steps, setSteps] = useState<StepDraft[]>(emptySteps());
  const [dirty, setDirty] = useState(false);
  const isModal = mode === "modal";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const concept = await getCurriculumConcept(token, conceptId, topicSource);
      setDisplayName(concept.display_name);
      const parsed = parseInitial(concept.vtse_template);
      setStrategyId(parsed.strategyId);
      setComparison(parsed.comparison);
      setSteps(parsed.steps);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load concept");
    } finally {
      setLoading(false);
    }
  }, [token, conceptId, topicSource]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [isModal, onClose]);

  useEffect(() => {
    if (isModal) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, isModal]);

  const strategyMeta = useMemo(
    () => STRATEGIES.find((s) => s.id === strategyId) || null,
    [strategyId]
  );

  function requestClose() {
    if (dirty && !confirm("Discard unsaved VTSE template changes?")) return;
    onClose?.();
  }

  function selectStrategy(id: VtseStrategyId) {
    if (strategyId && strategyId !== id && dirty) {
      if (!confirm("Switching template clears the current points. Continue?")) return;
    } else if (strategyId && strategyId !== id) {
      if (!confirm("Switch template? Points for the previous template will be cleared.")) return;
    }
    setStrategyId(id);
    setComparison(emptyComparison());
    setSteps(emptySteps(id === "cycle_process" ? 4 : 3));
    setDirty(true);
    setOkMsg(null);
  }

  function buildPayload(): ConceptVtseTemplate | null {
    if (!strategyId) return null;
    if (strategyId === "comparison_contrast") {
      return {
        strategy_id: strategyId,
        version: 1,
        payload: {
          left_label: comparison.left_label.trim(),
          right_label: comparison.right_label.trim(),
          rows: comparison.rows
            .map((r) => ({
              dimension: r.dimension.trim(),
              left: r.left.trim(),
              right: r.right.trim(),
            }))
            .filter((r) => r.left || r.right),
        },
      };
    }
    return {
      strategy_id: strategyId,
      version: 1,
      payload: {
        steps: steps
          .map((s) => ({
            label: s.label.trim(),
            summary: s.summary.trim() || s.label.trim(),
          }))
          .filter((s) => s.label),
      },
    };
  }

  async function save() {
    const payload = buildPayload();
    if (!payload) {
      setError("Select a VTSE template first");
      return;
    }
    setSaving(true);
    setError(null);
    setOkMsg(null);
    try {
      await updateCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        vtse_template: payload,
      });
      setDirty(false);
      setOkMsg("VTSE template saved — teaching will lock to this layout.");
      await load();
      await onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function clearTemplate() {
    if (!confirm("Clear the authored VTSE template? Auto-select will be used again.")) return;
    setSaving(true);
    setError(null);
    try {
      await updateCurriculumConcept(token, conceptId, {
        topic_source: topicSource,
        vtse_template: { strategy_id: "", version: 1, payload: {} },
      });
      setStrategyId(null);
      setComparison(emptyComparison());
      setSteps(emptySteps());
      setDirty(false);
      setOkMsg("Template cleared.");
      await onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Clear failed");
    } finally {
      setSaving(false);
    }
  }

  const body = loading ? (
    <div className="p-8 text-sm text-slate-500">Loading VTSE template…</div>
  ) : (
    <div className={cn("space-y-6", !isModal && "mx-auto max-w-5xl p-6")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            VTSE Template
          </p>
          <h1
            className={cn(
              "font-semibold text-slate-900 dark:text-slate-50",
              isModal ? "text-xl" : "text-2xl"
            )}
          >
            {displayName || "Concept"}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Pick the teaching layout students will see, then add short outline points.
            At teach time DeepSeek expands each point into a full teacher explanation in its
            own words — your text is the outline, not the spoken lesson.
          </p>
        </div>
        {isModal ? (
          <button
            type="button"
            onClick={requestClose}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            Close
          </button>
        ) : backHref ? (
          <Link
            href={backHref}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            Back to builder
          </Link>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
          {error}
        </div>
      ) : null}
      {okMsg ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
          {okMsg}
        </div>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          1. Choose template
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STRATEGIES.map((s) => {
            const active = strategyId === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => selectStrategy(s.id)}
                className={cn(
                  "rounded-xl border p-4 text-left transition",
                  active
                    ? "border-sky-500 bg-sky-50 ring-2 ring-sky-200 dark:border-sky-400 dark:bg-sky-950/40 dark:ring-sky-900"
                    : "border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-500"
                )}
              >
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">{s.label}</p>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{s.blurb}</p>
              </button>
            );
          })}
        </div>
      </section>

      {strategyId ? (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            2. Author points — {strategyMeta?.label}
          </h2>
          {strategyId === "comparison_contrast" ? (
            <ComparisonEditor
              value={comparison}
              onChange={(next) => {
                setComparison(next);
                setDirty(true);
              }}
              disabled={saving}
            />
          ) : (
            <StepsEditor
              strategyId={strategyId}
              steps={steps}
              onChange={(next) => {
                setSteps(next);
                setDirty(true);
              }}
              disabled={saving}
            />
          )}
        </section>
      ) : (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-600">
          Select a template above to begin authoring. Concepts without a template keep
          automatic strategy selection.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4 dark:border-slate-700">
        <button
          type="button"
          disabled={saving || !strategyId}
          onClick={() => void save()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {saving ? "Saving…" : "Save template"}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void clearTemplate()}
          className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 dark:border-slate-600 dark:text-slate-200"
        >
          Clear template
        </button>
        {dirty ? (
          <span className="text-xs text-amber-700 dark:text-amber-300">Unsaved changes</span>
        ) : null}
      </div>
    </div>
  );

  if (!isModal) {
    return body;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label="VTSE Template"
      onClick={requestClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="overflow-y-auto p-5 sm:p-6">{body}</div>
      </div>
    </div>
  );
}

function ComparisonEditor({
  value,
  onChange,
  disabled,
}: {
  value: ReturnType<typeof emptyComparison>;
  onChange: (v: ReturnType<typeof emptyComparison>) => void;
  disabled?: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-b from-slate-50 to-white dark:border-slate-700 dark:from-slate-900 dark:to-slate-950">
      <div className="grid grid-cols-2 gap-0 border-b border-slate-200 dark:border-slate-700">
        <div className="border-r border-slate-200 p-4 dark:border-slate-700">
          <label className="text-xs font-semibold uppercase tracking-wide text-sky-700 dark:text-sky-300">
            Left side
          </label>
          <input
            value={value.left_label}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, left_label: e.target.value })}
            placeholder="e.g. Humans"
            className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold dark:border-slate-600 dark:bg-slate-950"
          />
        </div>
        <div className="p-4">
          <label className="text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
            Right side
          </label>
          <input
            value={value.right_label}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, right_label: e.target.value })}
            placeholder="e.g. Robots"
            className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold dark:border-slate-600 dark:bg-slate-950"
          />
        </div>
      </div>

      <div className="space-y-3 p-4">
        {value.rows.map((row, idx) => (
          <div
            key={idx}
            className="rounded-xl border border-slate-200 bg-white/80 p-3 dark:border-slate-700 dark:bg-slate-900/60"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <input
                value={row.dimension}
                disabled={disabled}
                onChange={(e) => {
                  const rows = [...value.rows];
                  rows[idx] = { ...row, dimension: e.target.value };
                  onChange({ ...value, rows });
                }}
                placeholder={`Dimension ${idx + 1} (e.g. Living)`}
                className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-xs font-medium dark:border-slate-600 dark:bg-slate-950"
              />
              {value.rows.length > 2 ? (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    onChange({ ...value, rows: value.rows.filter((_, i) => i !== idx) })
                  }
                  className="shrink-0 text-xs text-rose-600"
                >
                  Remove
                </button>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <textarea
                value={row.left}
                disabled={disabled}
                rows={2}
                onChange={(e) => {
                  const rows = [...value.rows];
                  rows[idx] = { ...row, left: e.target.value };
                  onChange({ ...value, rows });
                }}
                placeholder="Left point…"
                className="w-full rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 text-sm dark:border-sky-900 dark:bg-sky-950/30"
              />
              <textarea
                value={row.right}
                disabled={disabled}
                rows={2}
                onChange={(e) => {
                  const rows = [...value.rows];
                  rows[idx] = { ...row, right: e.target.value };
                  onChange({ ...value, rows });
                }}
                placeholder="Right point…"
                className="w-full rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 text-sm dark:border-violet-900 dark:bg-violet-950/30"
              />
            </div>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onChange({
              ...value,
              rows: [...value.rows, { dimension: "", left: "", right: "" }],
            })
          }
          className="text-sm font-medium text-sky-700 dark:text-sky-300"
        >
          + Add point pair
        </button>
      </div>
    </div>
  );
}

function StepsEditor({
  strategyId,
  steps,
  onChange,
  disabled,
}: {
  strategyId: VtseStrategyId;
  steps: StepDraft[];
  onChange: (steps: StepDraft[]) => void;
  disabled?: boolean;
}) {
  const isCycle = strategyId === "cycle_process";
  const isHierarchy =
    strategyId === "hierarchy_concept_intro" || strategyId === "clustered_trait_list";

  return (
    <div
      className={cn(
        "rounded-2xl border border-slate-200 p-4 dark:border-slate-700",
        isCycle && "bg-gradient-to-br from-amber-50/40 to-white dark:from-amber-950/20 dark:to-slate-950",
        strategyId === "linear_process" &&
          "bg-gradient-to-b from-emerald-50/40 to-white dark:from-emerald-950/20 dark:to-slate-950",
        isHierarchy &&
          "bg-gradient-to-b from-indigo-50/30 to-white dark:from-indigo-950/20 dark:to-slate-950"
      )}
    >
      {isHierarchy ? (
        <div className="mb-4 rounded-lg border border-dashed border-indigo-200 bg-indigo-50/50 px-3 py-2 text-xs text-indigo-800 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-200">
          Root concept stays the microconcept name. Add child traits / nodes below.
        </div>
      ) : null}
      <ol className="space-y-3">
        {steps.map((step, idx) => (
          <li
            key={idx}
            className={cn(
              "flex gap-3 rounded-xl border border-slate-200 bg-white/90 p-3 dark:border-slate-700 dark:bg-slate-900/70",
              isCycle && idx === 0 && "ring-1 ring-amber-300/60"
            )}
          >
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white",
                isCycle ? "bg-amber-600" : strategyId === "linear_process" ? "bg-emerald-600" : "bg-indigo-600"
              )}
            >
              {isCycle ? ((idx % steps.length) + 1) : idx + 1}
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <input
                value={step.label}
                disabled={disabled}
                onChange={(e) => {
                  const next = [...steps];
                  next[idx] = { ...step, label: e.target.value };
                  onChange(next);
                }}
                placeholder={isHierarchy ? `Trait ${idx + 1}` : `Step ${idx + 1} label`}
                className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium dark:border-slate-600 dark:bg-slate-950"
              />
              <textarea
                value={step.summary}
                disabled={disabled}
                rows={2}
                onChange={(e) => {
                  const next = [...steps];
                  next[idx] = { ...step, summary: e.target.value };
                  onChange(next);
                }}
                placeholder="Point detail the AI should teach…"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-950"
              />
            </div>
            {steps.length > 3 ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(steps.filter((_, i) => i !== idx))}
                className="self-start text-xs text-rose-600"
              >
                Remove
              </button>
            ) : null}
          </li>
        ))}
      </ol>
      {isCycle ? (
        <p className="mt-3 text-xs text-amber-800 dark:text-amber-200">
          Cycle closes visually back to step 1 when taught.
        </p>
      ) : null}
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange([...steps, { label: "", summary: "" }])}
        className="mt-3 text-sm font-medium text-sky-700 dark:text-sky-300"
      >
        + Add {isHierarchy ? "trait" : "step"}
      </button>
    </div>
  );
}
