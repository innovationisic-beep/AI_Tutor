"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { updateClassSessionPlan } from "@/lib/api/classroom";
import { updateCatalogSessionPlan } from "@/lib/api/catalogClassroom";
import type { ClassSessionPlan } from "@/lib/types/classroom";

type SessionIntroductionEditorProps = {
  token: string;
  plan: ClassSessionPlan;
  planScope?: "teacher" | "catalog";
  disabled?: boolean;
  /** Called before save so callers can demote published plans to draft. */
  onBeforeSave?: () => Promise<void>;
  onSaved: (plan: ClassSessionPlan) => void;
  onToast: (message: string, variant?: "ok" | "err") => void;
};

export function SessionIntroductionEditor({
  token,
  plan,
  planScope = "teacher",
  disabled = false,
  onBeforeSave,
  onSaved,
  onToast,
}: SessionIntroductionEditorProps) {
  const [title, setTitle] = useState(plan.title);
  const [description, setDescription] = useState(plan.description ?? "");
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setTitle(plan.title);
    setDescription(plan.description ?? "");
    setJustSaved(false);
  }, [plan.id, plan.title, plan.description]);

  async function save() {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      onToast("Session title is required", "err");
      return;
    }
    setSaving(true);
    try {
      if (onBeforeSave) await onBeforeSave();
      const body = {
        title: trimmedTitle,
        description: description.trim(),
      };
      const updated =
        planScope === "catalog"
          ? await updateCatalogSessionPlan(token, plan.id, body)
          : await updateClassSessionPlan(token, plan.id, body);
      setJustSaved(true);
      onSaved(updated);
      onToast("Session introduction saved");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Save failed", "err");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 space-y-4 border-t border-slate-200 pt-4 dark:border-slate-700">
      <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
        Session introduction
      </h4>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        What to study and learning outcomes on the student Session Card come from the
        concepts included in this session plan.
      </p>
      <label className="block space-y-1">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Session title
        </span>
        <input
          type="text"
          value={title}
          disabled={disabled || saving}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Session description
        </span>
        <textarea
          value={description}
          disabled={disabled || saving}
          rows={3}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
      </label>
      {!disabled ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" size="sm" disabled={saving} onClick={() => void save()}>
            {saving ? "Saving…" : "Save introduction"}
          </Button>
          {justSaved ? (
            <span className="text-xs text-emerald-600 dark:text-emerald-400">Saved</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
