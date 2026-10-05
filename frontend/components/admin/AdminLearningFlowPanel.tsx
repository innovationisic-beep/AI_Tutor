"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createAdminPrerequisite,
  createAdminProgression,
  deleteAdminPrerequisite,
  deleteAdminProgression,
  getAdminPrerequisites,
  getAdminProgression,
} from "@/lib/api";
import type {
  AdminCatalogTopic,
  AdminPrerequisiteEdge,
  AdminProgressionEdge,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Loader2, Plus, Trash2 } from "lucide-react";

type ToastFn = (msg: string, variant?: "ok" | "err") => void;

type Props = {
  token: string;
  topicId: string;
  /** Same-subject catalog topics (admin topic list for selected subject). */
  sameSubjectTopics: AdminCatalogTopic[];
  /** Grade label for helper text (subject’s grade). */
  subjectGrade: string;
  onToast: ToastFn;
};

export function AdminLearningFlowPanel({
  token,
  topicId,
  sameSubjectTopics,
  subjectGrade,
  onToast,
}: Props) {
  const [prereqs, setPrereqs] = useState<AdminPrerequisiteEdge[]>([]);
  const [progression, setProgression] = useState<AdminProgressionEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyPrereq, setBusyPrereq] = useState<Set<string>>(() => new Set());
  const [busyProgId, setBusyProgId] = useState<Set<string>>(() => new Set());
  const [addingProg, setAddingProg] = useState(false);
  const [nextTopicId, setNextTopicId] = useState("");
  const [masteryDraft, setMasteryDraft] = useState("60");

  const eligibleTopics = useMemo(
    () => sameSubjectTopics.filter((t) => t.id !== topicId),
    [sameSubjectTopics, topicId]
  );

  const prereqIdByOther = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of prereqs) {
      m.set(e.prerequisite_topic_id, e.id);
    }
    return m;
  }, [prereqs]);

  const nextTopicIds = useMemo(
    () => new Set(progression.map((p) => p.recommended_next_topic_id)),
    [progression]
  );

  const progressionAddOptions = useMemo(
    () => eligibleTopics.filter((t) => !nextTopicIds.has(t.id)),
    [eligibleTopics, nextTopicIds]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [p, g] = await Promise.all([
        getAdminPrerequisites(token, topicId),
        getAdminProgression(token, topicId),
      ]);
      setPrereqs(p);
      setProgression(g);
    } catch (e) {
      onToast(
        e instanceof Error ? e.message : "Failed to load learning flow",
        "err"
      );
      setPrereqs([]);
      setProgression([]);
    } finally {
      setLoading(false);
    }
  }, [token, topicId, onToast]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const topicName = useCallback(
    (id: string) =>
      sameSubjectTopics.find((t) => t.id === id)?.topic_name ?? id,
    [sameSubjectTopics]
  );

  const setPrereqBusy = (otherId: string, on: boolean) => {
    setBusyPrereq((prev) => {
      const next = new Set(prev);
      if (on) next.add(otherId);
      else next.delete(otherId);
      return next;
    });
  };

  async function onTogglePrerequisite(otherTopicId: string, checked: boolean) {
    if (otherTopicId === topicId) return;
    if (checked) {
      setPrereqBusy(otherTopicId, true);
      try {
        const row = await createAdminPrerequisite(token, {
          topic_id: topicId,
          prerequisite_topic_id: otherTopicId,
        });
        setPrereqs((prev) => [...prev, row]);
        onToast("Prerequisite added");
      } catch (e) {
        onToast(
          e instanceof Error ? e.message : "Could not add prerequisite",
          "err"
        );
      } finally {
        setPrereqBusy(otherTopicId, false);
      }
    } else {
      const edgeId = prereqIdByOther.get(otherTopicId);
      if (!edgeId) return;
      setPrereqBusy(otherTopicId, true);
      try {
        await deleteAdminPrerequisite(token, edgeId);
        setPrereqs((prev) => prev.filter((x) => x.id !== edgeId));
        onToast("Prerequisite removed");
      } catch (e) {
        onToast(
          e instanceof Error ? e.message : "Could not remove prerequisite",
          "err"
        );
      } finally {
        setPrereqBusy(otherTopicId, false);
      }
    }
  }

  async function removeProgression(edge: AdminProgressionEdge) {
    setBusyProgId((s) => new Set(s).add(edge.id));
    try {
      await deleteAdminProgression(token, edge.id);
      setProgression((prev) => prev.filter((x) => x.id !== edge.id));
      onToast("Next topic removed");
    } catch (e) {
      onToast(
        e instanceof Error ? e.message : "Could not remove progression",
        "err"
      );
    } finally {
      setBusyProgId((s) => {
        const n = new Set(s);
        n.delete(edge.id);
        return n;
      });
    }
  }

  async function addProgression() {
    const nid = nextTopicId.trim();
    if (!nid || nid === topicId) {
      onToast("Choose a next topic", "err");
      return;
    }
    if (nextTopicIds.has(nid)) {
      onToast("That topic is already listed", "err");
      return;
    }
    let mastery = Number.parseInt(masteryDraft, 10);
    if (Number.isNaN(mastery)) mastery = 60;
    mastery = Math.min(100, Math.max(0, mastery));
    setAddingProg(true);
    try {
      const row = await createAdminProgression(token, {
        topic_id: topicId,
        recommended_next_topic_id: nid,
        minimum_mastery_to_recommend: mastery,
      });
      setProgression((prev) => [...prev, row]);
      setNextTopicId("");
      setMasteryDraft("60");
      onToast("Next topic added");
    } catch (e) {
      onToast(
        e instanceof Error ? e.message : "Could not add progression",
        "err"
      );
    } finally {
      setAddingProg(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50/80 py-12 text-sm text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400">
        <Loader2 className="size-5 animate-spin" />
        Loading learning flow…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Topics are limited to this subject
        {subjectGrade ? ` (grade ${subjectGrade})` : ""}. Cross-subject links are
        not available here.
      </p>

      <Card className="rounded-xl shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Prerequisites</CardTitle>
          <CardDescription>
            Topics students must complete before this
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label className="text-slate-700 dark:text-slate-200">
              Select prerequisites
            </Label>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Toggle topics to add or remove an edge. The current topic cannot be
              a prerequisite of itself.
            </p>
          </div>
          {eligibleTopics.length === 0 ? (
            <p className="text-sm text-slate-500">
              No other topics in this subject to link.
            </p>
          ) : (
            <ul
              className="custom-scrollbar max-h-52 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/50 p-3 dark:border-slate-700 dark:bg-slate-900/30"
              role="list"
            >
              {eligibleTopics.map((t) => {
                const checked = prereqIdByOther.has(t.id);
                const busy = busyPrereq.has(t.id);
                return (
                  <li key={t.id}>
                    <label
                      className={cn(
                        "flex cursor-pointer items-start gap-3 rounded-lg px-2 py-1.5 text-sm transition hover:bg-white dark:hover:bg-slate-800/80",
                        busy && "pointer-events-none opacity-60"
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 shrink-0 rounded border-slate-300"
                        checked={checked}
                        disabled={busy}
                        onChange={(ev) =>
                          void onTogglePrerequisite(t.id, ev.target.checked)
                        }
                      />
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {t.topic_name}
                      </span>
                      {busy ? (
                        <Loader2 className="ml-auto size-4 shrink-0 animate-spin text-slate-400" />
                      ) : null}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-xl shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Next topics</CardTitle>
          <CardDescription>Topics to recommend after this</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {progression.length > 0 ? (
            <ul className="space-y-2">
              {progression.map((edge) => {
                const busy = busyProgId.has(edge.id);
                return (
                  <li
                    key={edge.id}
                    className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/50 px-3 py-2 shadow-sm dark:border-slate-700 dark:bg-slate-900/30"
                  >
                    <div className="min-w-0 flex-1">
                      <Label className="text-xs text-slate-500 dark:text-slate-400">
                        Next topic
                      </Label>
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-50">
                        {topicName(edge.recommended_next_topic_id)}
                      </p>
                    </div>
                    <div className="w-24">
                      <Label className="text-xs text-slate-500 dark:text-slate-400">
                        Mastery %
                      </Label>
                      <p className="text-sm tabular-nums text-slate-800 dark:text-slate-200">
                        {edge.minimum_mastery_to_recommend}
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40"
                      disabled={busy}
                      onClick={() => void removeProgression(edge)}
                      aria-label="Remove next topic"
                    >
                      {busy ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4" />
                      )}
                    </Button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No next topics yet.</p>
          )}

          <div className="rounded-xl border border-dashed border-slate-200 bg-white/80 p-4 dark:border-slate-700 dark:bg-slate-950/40">
            <p className="mb-3 text-xs font-medium text-slate-600 dark:text-slate-300">
              Add recommendation
            </p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1 space-y-1.5">
                <Label htmlFor="lf-next-topic">Topic</Label>
                <select
                  id="lf-next-topic"
                  className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-600 dark:bg-slate-950"
                  value={nextTopicId}
                  onChange={(e) => setNextTopicId(e.target.value)}
                  disabled={addingProg || progressionAddOptions.length === 0}
                >
                  <option value="">Select topic…</option>
                  {progressionAddOptions.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.topic_name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-full space-y-1.5 sm:w-28">
                <Label htmlFor="lf-mastery">Mastery %</Label>
                <Input
                  id="lf-mastery"
                  type="number"
                  min={0}
                  max={100}
                  inputMode="numeric"
                  value={masteryDraft}
                  onChange={(e) => setMasteryDraft(e.target.value)}
                  disabled={addingProg}
                  className="h-9"
                />
              </div>
              <Button
                type="button"
                size="sm"
                className="h-9 shrink-0"
                disabled={
                  addingProg ||
                  !nextTopicId ||
                  progressionAddOptions.length === 0
                }
                onClick={() => void addProgression()}
              >
                {addingProg ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <>
                    <Plus className="mr-1 size-4" />
                    Add
                  </>
                )}
              </Button>
            </div>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              Mastery threshold: 0–100. Default 60. Duplicate next topics are
              blocked.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
