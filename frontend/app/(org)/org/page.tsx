"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import {
  createClass,
  createSubject,
  createTeacher,
  deleteOrgClass,
  deleteOrgSubject,
  deleteOrgTeacher,
  getOrgStructure,
  listOrgTeachers,
  updateOrgClass,
  updateOrgSubject,
  updateOrgTeacher,
} from "@/lib/api";
import type { OrgStructure, OrgTeacher } from "@/lib/types";
import { CurriculumSubjectLinkModal } from "@/components/org/CurriculumSubjectLinkModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}

function normalizeSubjectName(name: string): string {
  return name.trim().toLowerCase();
}

function duplicateSubjectNameKeysForClass(
  structure: OrgStructure,
  classId: string
): Set<string> {
  const c = structure.classes.find((x) => x.id === classId);
  if (!c) return new Set();
  const counts = new Map<string, number>();
  for (const s of c.subjects) {
    const k = normalizeSubjectName(s.name);
    if (!k) continue;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const dups = new Set<string>();
  for (const [k, n] of counts) {
    if (n > 1) dups.add(k);
  }
  return dups;
}

type SubjectRow = {
  key: string;
  serverId: string | null;
  name: string;
  /** Last saved name from server; used to detect renames. */
  originalName?: string;
  curriculum_subject_id?: string | null;
};

type ConfirmModalState = {
  title: string;
  message: string;
  destructive?: boolean;
  confirmLabel?: string;
  /** When true, modal shows a “force delete” checkbox (class with subjects). */
  showForceOption?: boolean;
  onConfirm: (opts: { force: boolean }) => Promise<void>;
} | null;

const checkboxClass =
  "rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600";

export default function OrganizationPanelPage() {
  const { token, ready } = useAuth();
  const [structure, setStructure] = useState<OrgStructure>({ classes: [] });
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);
  const [subjectRows, setSubjectRows] = useState<SubjectRow[]>([]);

  const [className, setClassName] = useState("");
  const [classBusy, setClassBusy] = useState(false);
  const [classMsg, setClassMsg] = useState<string | null>(null);

  const [subjectSaveBusy, setSubjectSaveBusy] = useState(false);
  const [subjectMsg, setSubjectMsg] = useState<string | null>(null);

  const [editingClassId, setEditingClassId] = useState<string | null>(null);
  const [classEditName, setClassEditName] = useState("");
  const [classEditBusy, setClassEditBusy] = useState(false);

  const [teachers, setTeachers] = useState<OrgTeacher[]>([]);
  const [teachersError, setTeachersError] = useState<string | null>(null);
  const [teacherEditId, setTeacherEditId] = useState<string | null>(null);

  const [confirmModal, setConfirmModal] = useState<ConfirmModalState>(null);
  const [confirmForce, setConfirmForce] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const [tEmail, setTEmail] = useState("");
  const [tPassword, setTPassword] = useState("");
  const [tClasses, setTClasses] = useState<string[]>([]);
  const [tSubjects, setTSubjects] = useState<string[]>([]);
  const [tBusy, setTBusy] = useState(false);
  const [tMsg, setTMsg] = useState<string | null>(null);

  const [linkModal, setLinkModal] = useState<{
    classId: string;
    subjectId: string;
    subjectName: string;
    initialCurriculumSubjectId: string | null;
  } | null>(null);

  const [toast, setToast] = useState<{
    text: string;
    variant: "ok" | "err";
  } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback(
    (message: string, variant: "ok" | "err" = "ok") => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
      setToast({ text: message, variant });
      toastTimer.current = setTimeout(() => {
        setToast(null);
        toastTimer.current = null;
      }, 3800);
    },
    []
  );

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoadError(null);
    try {
      const s = await getOrgStructure(token);
      setStructure(s);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load structure");
    }
  }, [token]);

  const refreshTeachers = useCallback(async () => {
    if (!token) return;
    setTeachersError(null);
    try {
      const list = await listOrgTeachers(token);
      setTeachers(list);
    } catch (e) {
      setTeachersError(
        e instanceof Error ? e.message : "Failed to load teachers"
      );
    }
  }, [token]);

  useEffect(() => {
    if (!ready || !token) return;
    void refresh();
  }, [ready, token, refresh]);

  useEffect(() => {
    if (!ready || !token) return;
    void refreshTeachers();
  }, [ready, token, refreshTeachers]);

  useEffect(() => {
    if (
      selectedClassId &&
      !structure.classes.some((c) => c.id === selectedClassId)
    ) {
      setSelectedClassId(null);
    }
  }, [structure, selectedClassId]);

  useEffect(() => {
    if (!selectedClassId) {
      setSubjectRows([]);
      setSubjectMsg(null);
      return;
    }
    const c = structure.classes.find((x) => x.id === selectedClassId);
    if (!c) {
      setSubjectRows([]);
      return;
    }
    setSubjectRows(
      c.subjects.map((s) => ({
        key: s.id,
        serverId: s.id,
        name: s.name,
        originalName: s.name,
        curriculum_subject_id: s.curriculum_subject_id,
      }))
    );
    setSubjectMsg(null);
  }, [selectedClassId, structure]);

  const selectedClass = useMemo(
    () => structure.classes.find((c) => c.id === selectedClassId) ?? null,
    [structure.classes, selectedClassId]
  );

  const classNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of structure.classes) m.set(c.id, c.name);
    return m;
  }, [structure.classes]);

  const subjectNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of structure.classes) {
      for (const s of c.subjects) {
        if (!m.has(s.id)) m.set(s.id, s.name);
      }
    }
    return m;
  }, [structure.classes]);

  const dupKeys = useMemo(
    () =>
      selectedClassId
        ? duplicateSubjectNameKeysForClass(structure, selectedClassId)
        : new Set<string>(),
    [structure, selectedClassId]
  );

  const teacherSubjectOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const cid of tClasses) {
      const cls = structure.classes.find((c) => c.id === cid);
      if (!cls) continue;
      for (const s of cls.subjects) {
        if (!map.has(s.id)) map.set(s.id, s.name);
      }
    }
    return Array.from(map.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [structure, tClasses]);

  useEffect(() => {
    const valid = new Set(teacherSubjectOptions.map((s) => s.id));
    setTSubjects((prev) => prev.filter((id) => valid.has(id)));
  }, [teacherSubjectOptions]);

  async function onAddClass(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !className.trim()) return;
    setClassMsg(null);
    setClassBusy(true);
    try {
      const created = await createClass(token, className.trim());
      setClassName("");
      await refresh();
      setSelectedClassId(created.id);
      setClassMsg("Class added.");
    } catch (err) {
      setClassMsg(err instanceof Error ? err.message : "Failed");
    } finally {
      setClassBusy(false);
    }
  }

  function addSubjectRow() {
    setSubjectRows((r) => [
      ...r,
      { key: `new-${Date.now()}-${Math.random().toString(36).slice(2)}`, serverId: null, name: "" },
    ]);
  }

  function updateSubjectRow(key: string, name: string) {
    setSubjectRows((rows) =>
      rows.map((row) => (row.key === key ? { ...row, name } : row))
    );
  }

  async function onSaveSubjects(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !selectedClassId) return;
    const toCreate = subjectRows.filter((r) => !r.serverId && r.name.trim());
    const toUpdate = subjectRows.filter((r) => {
      if (!r.serverId || !r.name.trim()) return false;
      const orig = (r.originalName ?? "").trim();
      return r.name.trim() !== orig;
    });
    if (toCreate.length === 0 && toUpdate.length === 0) {
      setSubjectMsg(
        "Nothing to save — add new subjects or change an existing name."
      );
      return;
    }
    setSubjectMsg(null);
    setSubjectSaveBusy(true);
    try {
      await Promise.all([
        ...toCreate.map((r) =>
          createSubject(token, selectedClassId, r.name.trim())
        ),
        ...toUpdate.map((r) =>
          updateOrgSubject(
            token,
            selectedClassId,
            r.serverId!,
            r.name.trim()
          )
        ),
      ]);
      await refresh();
      showToast("Updated successfully");
      const parts: string[] = [];
      if (toCreate.length) parts.push(`${toCreate.length} added`);
      if (toUpdate.length) parts.push(`${toUpdate.length} renamed`);
      setSubjectMsg(parts.join(", ") + ".");
    } catch (err) {
      setSubjectMsg(err instanceof Error ? err.message : "Failed to save");
      showToast(
        err instanceof Error ? err.message : "Failed to save",
        "err"
      );
    } finally {
      setSubjectSaveBusy(false);
    }
  }

  function openDeleteSubjectConfirm(row: SubjectRow) {
    if (!token || !selectedClassId || !row.serverId) return;
    setConfirmModal({
      title: "Delete subject",
      message: `Remove “${row.name.trim() || "this subject"}” from this class? This cannot be undone. Teachers assigned to this subject must be unassigned first.`,
      destructive: true,
      confirmLabel: "Delete subject",
      onConfirm: async () => {
        await deleteOrgSubject(token, selectedClassId!, row.serverId!);
        await refresh();
        showToast("Deleted successfully");
      },
    });
    setConfirmForce(false);
  }

  async function saveClassEdit(classId: string) {
    if (!token || !classEditName.trim()) return;
    setClassEditBusy(true);
    setClassMsg(null);
    try {
      await updateOrgClass(token, classId, classEditName.trim());
      setEditingClassId(null);
      setClassEditName("");
      await refresh();
      showToast("Updated successfully");
      setClassMsg("Class updated.");
    } catch (err) {
      setClassMsg(err instanceof Error ? err.message : "Failed to update");
      showToast(
        err instanceof Error ? err.message : "Failed to update",
        "err"
      );
    } finally {
      setClassEditBusy(false);
    }
  }

  function openDeleteClassConfirm(c: OrgStructure["classes"][number]) {
    if (!token) return;
    const n = c.subjects.length;
    setConfirmModal({
      title: "Delete class",
      message:
        n > 0
          ? `This class has ${n} subject(s). Deleting it will remove the class and all its subjects, and update teacher assignments.`
          : `Delete class “${c.name}”? This cannot be undone.`,
      destructive: true,
      confirmLabel: "Delete class",
      showForceOption: n > 0,
      onConfirm: async ({ force }) => {
        await deleteOrgClass(token, c.id, force);
        if (selectedClassId === c.id) setSelectedClassId(null);
        await refresh();
        await refreshTeachers();
        showToast("Deleted successfully");
      },
    });
    setConfirmForce(false);
  }

  async function onTeacherSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setTMsg(null);
    setTBusy(true);
    try {
      if (teacherEditId) {
        await updateOrgTeacher(token, teacherEditId, {
          email: tEmail.trim(),
          assigned_classes: tClasses,
          assigned_subjects: tSubjects,
        });
        setTeacherEditId(null);
        setTEmail("");
        setTPassword("");
        setTClasses([]);
        setTSubjects([]);
        setTMsg("Teacher updated.");
        showToast("Updated successfully");
      } else {
        await createTeacher(token, {
          email: tEmail.trim(),
          password: tPassword,
          assigned_classes: tClasses,
          assigned_subjects: tSubjects,
        });
        setTEmail("");
        setTPassword("");
        setTClasses([]);
        setTSubjects([]);
        setTMsg("Teacher created.");
        showToast("Teacher created");
      }
      await refreshTeachers();
    } catch (err) {
      setTMsg(err instanceof Error ? err.message : "Failed");
      showToast(err instanceof Error ? err.message : "Failed", "err");
    } finally {
      setTBusy(false);
    }
  }

  function startEditTeacher(t: OrgTeacher) {
    setTeacherEditId(t.id);
    setTEmail(t.email);
    setTPassword("");
    setTClasses([...t.assigned_classes]);
    setTSubjects([...t.assigned_subjects]);
    setTMsg(null);
  }

  function cancelTeacherEdit() {
    setTeacherEditId(null);
    setTEmail("");
    setTPassword("");
    setTClasses([]);
    setTSubjects([]);
    setTMsg(null);
  }

  function openDeleteTeacherConfirm(t: OrgTeacher) {
    if (!token) return;
    setConfirmModal({
      title: "Delete teacher",
      message: `Remove teacher ${t.email}? Their account will be deleted from this organization.`,
      destructive: true,
      confirmLabel: "Delete teacher",
      onConfirm: async () => {
        await deleteOrgTeacher(token, t.id);
        if (teacherEditId === t.id) cancelTeacherEdit();
        await refreshTeachers();
        showToast("Deleted successfully");
      },
    });
    setConfirmForce(false);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <CurriculumSubjectLinkModal
        open={linkModal != null}
        onOpenChange={(o) => {
          if (!o) setLinkModal(null);
        }}
        token={token}
        classId={linkModal?.classId ?? ""}
        subjectId={linkModal?.subjectId ?? ""}
        orgSubjectName={linkModal?.subjectName ?? ""}
        initialCurriculumSubjectId={linkModal?.initialCurriculumSubjectId}
        onLinked={() => void refresh()}
        onToast={showToast}
      />

      {toast ? (
        <div
          className={cn(
            "fixed bottom-6 right-6 z-[60] max-w-sm rounded-xl border px-4 py-3 text-sm shadow-lg",
            toast.variant === "err"
              ? "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/90 dark:text-red-100"
              : "border-slate-200 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50"
          )}
          role="status"
        >
          {toast.text}
        </div>
      ) : null}

      {confirmModal ? (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="org-confirm-title"
        >
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900">
            <h2
              id="org-confirm-title"
              className="text-lg font-semibold text-slate-900 dark:text-slate-50"
            >
              {confirmModal.title}
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              {confirmModal.message}
            </p>
            {confirmModal.showForceOption ? (
              <label className="mt-4 flex cursor-pointer items-start gap-2 text-sm text-slate-800 dark:text-slate-200">
                <input
                  type="checkbox"
                  className={checkboxClass}
                  checked={confirmForce}
                  onChange={(e) => setConfirmForce(e.target.checked)}
                />
                <span>
                  I understand — delete this class and all its subjects (required
                  when the class is not empty).
                </span>
              </label>
            ) : null}
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={confirmBusy}
                onClick={() => {
                  setConfirmModal(null);
                  setConfirmForce(false);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant={confirmModal.destructive ? "destructive" : "default"}
                disabled={
                  confirmBusy ||
                  (Boolean(confirmModal.showForceOption) && !confirmForce)
                }
                onClick={async () => {
                  if (
                    confirmModal.showForceOption &&
                    !confirmForce
                  ) {
                    return;
                  }
                  setConfirmBusy(true);
                  try {
                    await confirmModal.onConfirm({
                      force: confirmModal.showForceOption ? confirmForce : false,
                    });
                    setConfirmModal(null);
                    setConfirmForce(false);
                  } catch (err) {
                    showToast(
                      err instanceof Error ? err.message : "Action failed",
                      "err"
                    );
                  } finally {
                    setConfirmBusy(false);
                  }
                }}
              >
                {confirmBusy
                  ? "…"
                  : confirmModal.confirmLabel ?? "Confirm"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Organization panel
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Pick a class, manage subjects, then invite teachers.
        </p>
        <Link
          href="/"
          className="mt-3 inline-block text-sm font-medium text-blue-600 underline-offset-4 hover:underline dark:text-blue-400"
        >
          Home
        </Link>
      </div>

      {loadError ? (
        <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="rounded-xl p-4 shadow-sm">
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Classes</CardTitle>
            <CardDescription>
              Select a class to edit subjects on the right.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 p-0">
            <form
              onSubmit={onAddClass}
              className="flex flex-col gap-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700"
            >
              <Label htmlFor="org-class-name">New class name</Label>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <Input
                  id="org-class-name"
                  value={className}
                  onChange={(e) => setClassName(e.target.value)}
                  placeholder="e.g. Grade 9"
                  disabled={classBusy}
                  className="flex-1"
                />
                <Button
                  type="submit"
                  disabled={classBusy || !className.trim()}
                >
                  {classBusy ? "Adding…" : "Add class"}
                </Button>
              </div>
              {classMsg ? (
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  {classMsg}
                </p>
              ) : null}
            </form>

            <div className="space-y-2">
              {structure.classes.length === 0 ? (
                <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-700">
                  No classes yet. Add one above.
                </p>
              ) : (
                <ul className="space-y-2">
                  {structure.classes.map((c) => {
                    const active = c.id === selectedClassId;
                    const editing = editingClassId === c.id;
                    return (
                      <li
                        key={c.id}
                        className={cn(
                          "rounded-xl border px-3 py-3 text-sm transition",
                          active
                            ? "border-blue-500 bg-blue-50 dark:border-blue-500 dark:bg-blue-950/40"
                            : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
                        )}
                      >
                        {editing ? (
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                            <Input
                              value={classEditName}
                              onChange={(e) => setClassEditName(e.target.value)}
                              disabled={classEditBusy}
                              className="flex-1"
                              aria-label="Class name"
                            />
                            <div className="flex flex-wrap gap-2">
                              <Button
                                type="button"
                                size="sm"
                                disabled={
                                  classEditBusy || !classEditName.trim()
                                }
                                onClick={() => void saveClassEdit(c.id)}
                              >
                                {classEditBusy ? "Saving…" : "Save"}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={classEditBusy}
                                onClick={() => {
                                  setEditingClassId(null);
                                  setClassEditName("");
                                }}
                              >
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                            <button
                              type="button"
                              onClick={() => setSelectedClassId(c.id)}
                              className={cn(
                                "min-w-0 flex-1 rounded-lg px-1 py-0.5 text-left font-medium",
                                active
                                  ? "text-blue-950 dark:text-blue-50"
                                  : "text-slate-900 hover:underline dark:text-slate-50"
                              )}
                            >
                              <span className="block truncate">{c.name}</span>
                              <span className="mt-0.5 block text-xs font-normal text-slate-500">
                                {c.subjects.length} subject
                                {c.subjects.length === 1 ? "" : "s"}
                              </span>
                            </button>
                            <div className="flex shrink-0 flex-wrap gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setEditingClassId(c.id);
                                  setClassEditName(c.name);
                                }}
                              >
                                Edit
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="destructive"
                                onClick={() => openDeleteClassConfirm(c)}
                              >
                                Delete
                              </Button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void refresh()}
            >
              Refresh structure
            </Button>
          </CardContent>
        </Card>

        <Card
          className={cn(
            "rounded-xl p-4 shadow-sm",
            !selectedClassId && "opacity-90"
          )}
        >
          <CardHeader className="p-0 pb-4">
            <CardTitle className="text-lg">Subjects</CardTitle>
            <CardDescription>
              {selectedClass
                ? `Managing: ${selectedClass.name}`
                : "Select a class to manage subjects."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 p-0">
            {!selectedClassId ? (
              <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
                Select a class to manage subjects
              </div>
            ) : (
              <>
                {dupKeys.size > 0 ? (
                  <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/50 dark:text-amber-100">
                    Warning: duplicate subject names in this class. Clean up extras
                    so curriculum links stay consistent.
                  </p>
                ) : null}

                <form onSubmit={onSaveSubjects} className="space-y-3">
                  <div className="space-y-2">
                    {subjectRows.length === 0 ? (
                      <p className="text-sm text-slate-500">
                        No subjects yet. Add rows below, then save.
                      </p>
                    ) : null}
                    {subjectRows.map((row) => {
                      const isExisting = row.serverId != null;
                      const dupName =
                        isExisting &&
                        normalizeSubjectName(row.name) &&
                        dupKeys.has(normalizeSubjectName(row.name));
                      const cs = row.curriculum_subject_id;
                      const linked = Boolean(
                        cs != null && String(cs).trim().length > 0
                      );
                      return (
                        <div
                          key={row.key}
                          className="rounded-xl border border-slate-200 p-3 dark:border-slate-700"
                        >
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                            <Input
                              value={row.name}
                              onChange={(e) =>
                                updateSubjectRow(row.key, e.target.value)
                              }
                              placeholder="Subject name"
                              disabled={subjectSaveBusy}
                              className="flex-1"
                            />
                            <div className="flex flex-wrap items-center gap-2">
                              {isExisting ? (
                                <>
                                  {dupName ? (
                                    <span className="text-[10px] font-semibold uppercase text-amber-700 dark:text-amber-300">
                                      Duplicate
                                    </span>
                                  ) : null}
                                  {linked ? (
                                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-900 dark:bg-emerald-950/80 dark:text-emerald-100">
                                      Linked
                                    </span>
                                  ) : (
                                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-950 dark:bg-amber-950/50 dark:text-amber-100">
                                      Not linked
                                    </span>
                                  )}
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={!selectedClassId || !row.serverId}
                                    onClick={() =>
                                      setLinkModal({
                                        classId: selectedClassId!,
                                        subjectId: row.serverId!,
                                        subjectName: row.name,
                                        initialCurriculumSubjectId:
                                          cs != null && String(cs).trim()
                                            ? String(cs).trim()
                                            : null,
                                      })
                                    }
                                  >
                                    {linked ? "Change link" : "Link curriculum"}
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="destructive"
                                    disabled={subjectSaveBusy}
                                    onClick={() =>
                                      openDeleteSubjectConfirm(row)
                                    }
                                  >
                                    Delete
                                  </Button>
                                </>
                              ) : null}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={addSubjectRow}
                      disabled={subjectSaveBusy}
                    >
                      + Add subject row
                    </Button>
                    <Button type="submit" disabled={subjectSaveBusy}>
                      {subjectSaveBusy ? "Saving…" : "Save subjects"}
                    </Button>
                  </div>
                  {subjectMsg ? (
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {subjectMsg}
                    </p>
                  ) : null}
                </form>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-xl p-4 shadow-sm">
        <CardHeader className="p-0 pb-4">
          <CardTitle className="text-lg">Teachers</CardTitle>
          <CardDescription>
            Teachers in your organization. Use Edit to change assignments or
            email.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 p-0">
          {teachersError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              {teachersError}
            </p>
          ) : null}
          {teachers.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-700">
              No teachers yet. Create one below.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {teachers.map((t) => {
                const classLabels = t.assigned_classes
                  .map((id) => classNameById.get(id) ?? id)
                  .join(", ");
                const subjectLabels = t.assigned_subjects
                  .map((id) => subjectNameById.get(id) ?? id)
                  .join(", ");
                return (
                  <div
                    key={t.id}
                    className="rounded-xl border border-slate-200 p-4 dark:border-slate-700"
                  >
                    <p className="font-medium text-slate-900 dark:text-slate-50">
                      {t.email}
                    </p>
                    <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">
                        Classes:{" "}
                      </span>
                      {classLabels || "—"}
                    </p>
                    <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">
                        Subjects:{" "}
                      </span>
                      {subjectLabels || "—"}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => startEditTeacher(t)}
                      >
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        onClick={() => openDeleteTeacherConfirm(t)}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refreshTeachers()}
          >
            Refresh teachers
          </Button>
        </CardContent>
      </Card>

      <Card className="rounded-xl p-4 shadow-sm">
        <CardHeader className="p-0 pb-4">
          <CardTitle className="text-lg">
            {teacherEditId ? "Edit teacher" : "Create teacher"}
          </CardTitle>
          <CardDescription>
            Choose classes first; only subjects from those classes appear below.
            No manual user IDs required.
            {teacherEditId
              ? " Password is not changed when editing."
              : null}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <form onSubmit={onTeacherSubmit} className="space-y-6">
            <div
              className={cn(
                "grid gap-4",
                teacherEditId ? "sm:grid-cols-1" : "sm:grid-cols-2"
              )}
            >
              <div className="space-y-2">
                <Label htmlFor="org-t-email">Email</Label>
                <Input
                  id="org-t-email"
                  type="email"
                  value={tEmail}
                  onChange={(e) => setTEmail(e.target.value)}
                  autoComplete="off"
                  disabled={tBusy}
                  required
                />
              </div>
              {teacherEditId ? null : (
                <div className="space-y-2">
                  <Label htmlFor="org-t-password">Password</Label>
                  <Input
                    id="org-t-password"
                    type="password"
                    value={tPassword}
                    onChange={(e) => setTPassword(e.target.value)}
                    autoComplete="new-password"
                    disabled={tBusy}
                    required
                    minLength={8}
                  />
                </div>
              )}
            </div>

            <div className="grid gap-6 md:grid-cols-2">
              <fieldset className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
                <legend className="px-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Classes
                </legend>
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {structure.classes.length === 0 ? (
                    <p className="text-xs text-slate-500">Add classes first.</p>
                  ) : (
                    structure.classes.map((c) => (
                      <label
                        key={c.id}
                        className="flex items-center gap-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          className={checkboxClass}
                          checked={tClasses.includes(c.id)}
                          onChange={() =>
                            setTClasses((prev) => toggleId(prev, c.id))
                          }
                        />
                        {c.name}
                      </label>
                    ))
                  )}
                </div>
              </fieldset>

              <fieldset className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
                <legend className="px-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Subjects
                </legend>
                <div className="max-h-48 space-y-2 overflow-y-auto">
                  {tClasses.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      Select at least one class to see subjects.
                    </p>
                  ) : teacherSubjectOptions.length === 0 ? (
                    <p className="text-xs text-slate-500">
                      No subjects in the selected classes yet.
                    </p>
                  ) : (
                    teacherSubjectOptions.map((s) => (
                      <label
                        key={s.id}
                        className="flex items-center gap-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          className={checkboxClass}
                          checked={tSubjects.includes(s.id)}
                          onChange={() =>
                            setTSubjects((prev) => toggleId(prev, s.id))
                          }
                        />
                        {s.name}
                      </label>
                    ))
                  )}
                </div>
              </fieldset>
            </div>

            <div className="flex flex-wrap gap-2">
              {teacherEditId ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={tBusy}
                  onClick={cancelTeacherEdit}
                >
                  Cancel edit
                </Button>
              ) : null}
              <Button type="submit" disabled={tBusy}>
                {tBusy
                  ? teacherEditId
                    ? "Updating…"
                    : "Creating…"
                  : teacherEditId
                    ? "Update teacher"
                    : "Create teacher"}
              </Button>
            </div>
            {tMsg ? (
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {tMsg}
              </p>
            ) : null}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
