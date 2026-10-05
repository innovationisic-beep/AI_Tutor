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
  createTeacherPrerequisite,
  createTeacherProgression,
  deleteTeacherPrerequisite,
  deleteTeacherProgression,
  getTeacherPrerequisites,
  getTeacherProgression,
} from "@/lib/api";
import type {
  AdminPrerequisiteEdge,
  AdminProgressionEdge,
  TeacherTopicRecord,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Loader2, Plus, Trash2 } from "lucide-react";

type ToastFn = (msg: string, variant?: "ok" | "err") => void;

function prereqEdgeForPeer(
  prereqs: AdminPrerequisiteEdge[],
  peer: TeacherTopicRecord
): AdminPrerequisiteEdge | undefined {
  return prereqs.find((e) => {
    if (e.prerequisite_topic_id === peer.id) return true;
    const link = peer.curriculum_topic_id?.trim();
    return Boolean(link && e.prerequisite_topic_id === link);
  });
}

function progressionCoversPeer(
  progression: AdminProgressionEdge[],
  peer: TeacherTopicRecord
): boolean {
  return progression.some((e) => {
    if (e.recommended_next_topic_id === peer.id) return true;
    const link = peer.curriculum_topic_id?.trim();
    return Boolean(link && e.recommended_next_topic_id === link);
  });
}

function topicLabel(id: string, peers: TeacherTopicRecord[]): string {
  const byTt = peers.find((t) => t.id === id);
  if (byTt) return byTt.topic_name;
  const byCat = peers.find((t) => t.curriculum_topic_id === id);
  if (byCat) return byCat.topic_name;
  return id;
}

type Props = {
  token: string;
  /** Current TeacherTopic id */
  teacherTopicId: string;
  /** All TeacherTopic rows for this class + subject */
  peerTopics: TeacherTopicRecord[];
  onToast: ToastFn;
};

export function TeacherLearningFlowPanel({
  token,
  teacherTopicId,
  peerTopics,
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

  const eligiblePeers = useMemo(
    () => peerTopics.filter((t) => t.id !== teacherTopicId),
    [peerTopics, teacherTopicId]
  );

  const progressionAddOptions = useMemo(
    () =>
      eligiblePeers.filter((p) => !progressionCoversPeer(progression, p)),
    [eligiblePeers, progression]
  );

  const loadAll = useCallback(
    async (quiet?: boolean) => {
      if (!quiet) setLoading(true);
      try {
        const [p, g] = await Promise.all([
          getTeacherPrerequisites(token, teacherTopicId),
          getTeacherProgression(token, teacherTopicId),
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
        if (!quiet) setLoading(false);
      }
    },
    [token, teacherTopicId, onToast]
  );

  useEffect(() => {
    void loadAll(false);
  }, [loadAll]);

  const setPrereqBusy = (peerId: string, on: boolean) => {
    setBusyPrereq((prev) => {
      const next = new Set(prev);
      if (on) next.add(peerId);
      else next.delete(peerId);
      return next;
    });
  };

  async function onTogglePrerequisite(
    peer: TeacherTopicRecord,
    checked: boolean
  ) {
    if (peer.id === teacherTopicId) return;
    if (checked) {
      setPrereqBusy(peer.id, true);
      try {
        await createTeacherPrerequisite(token, {
          topic_id: teacherTopicId,
          prerequisite_topic_id: peer.id,
        });
        onToast("Prerequisite added");
        await loadAll(true);
      } catch (e) {
        onToast(
          e instanceof Error ? e.message : "Could not add prerequisite",
          "err"
        );
      } finally {
        setPrereqBusy(peer.id, false);
      }
    } else {
      const edge = prereqEdgeForPeer(prereqs, peer);
      if (!edge) return;
      setPrereqBusy(peer.id, true);
      try {
        await deleteTeacherPrerequisite(token, edge.id);
        onToast("Prerequisite removed");
        await loadAll(true);
      } catch (e) {
        onToast(
          e instanceof Error
            ? e.message
            : "Could not remove prerequisite (catalog-only edges cannot be deleted here)",
          "err"
        );
      } finally {
        setPrereqBusy(peer.id, false);
      }
    }
  }

  async function removeProgression(edge: AdminProgressionEdge) {
    setBusyProgId((s) => new Set(s).add(edge.id));
    try {
      await deleteTeacherProgression(token, edge.id);
      onToast("Next topic removed");
      await loadAll(true);
    } catch (e) {
      onToast(
        e instanceof Error
          ? e.message
          : "Could not remove progression (catalog-only edges cannot be deleted here)",
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
    if (!nid || nid === teacherTopicId) {
      onToast("Choose a next topic", "err");
      return;
    }
    const peer = peerTopics.find((t) => t.id === nid);
    if (peer && progressionCoversPeer(progression, peer)) {
      onToast("That topic is already listed", "err");
      return;
    }
    let mastery = Number.parseInt(masteryDraft, 10);
    if (Number.isNaN(mastery)) mastery = 60;
    mastery = Math.min(100, Math.max(0, mastery));
    setAddingProg(true);
    try {
      await createTeacherProgression(token, {
        topic_id: teacherTopicId,
        recommended_next_topic_id: nid,
        minimum_mastery_to_recommend: mastery,
      });
      setNextTopicId("");
      setMasteryDraft("60");
      onToast("Next topic added");
      await loadAll(true);
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
        Only your topics for this class and subject appear here. The server may
        fall back to the global catalog graph until you add or change links—then
        your organization copy is used.
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
              Toggle other teacher topics. Adding a link stores it for your
              organization. Removing catalog-only edges may require adding your
              own links first.
            </p>
          </div>
          {eligiblePeers.length === 0 ? (
            <p className="text-sm text-slate-500">
              No other topics in this class/subject to link.
            </p>
          ) : (
            <ul
              className="custom-scrollbar max-h-52 space-y-2 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/50 p-3 dark:border-slate-700 dark:bg-slate-900/30"
              role="list"
            >
              {eligiblePeers.map((p) => {
                const edge = prereqEdgeForPeer(prereqs, p);
                const checked = edge != null;
                const busy = busyPrereq.has(p.id);
                return (
                  <li key={p.id}>
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
                          void onTogglePrerequisite(p, ev.target.checked)
                        }
                      />
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {p.topic_name}
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
                        {topicLabel(edge.recommended_next_topic_id, peerTopics)}
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
                <Label htmlFor="tlf-next-topic">Topic</Label>
                <select
                  id="tlf-next-topic"
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
                <Label htmlFor="tlf-mastery">Mastery %</Label>
                <Input
                  id="tlf-mastery"
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
