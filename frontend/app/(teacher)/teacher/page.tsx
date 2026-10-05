"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { getOrgStructure } from "@/lib/api";
import type { OrgClassWithSubjects, OrgNamedItem, OrgStructure } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const selectClassName = cn(
  "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm transition-colors",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2",
  "disabled:cursor-not-allowed disabled:opacity-50",
  "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus-visible:ring-slate-600"
);

export default function TeacherPanelPage() {
  const router = useRouter();
  const { token, user } = useAuth();

  const [structure, setStructure] = useState<OrgStructure>({ classes: [] });
  const [structureLoading, setStructureLoading] = useState(true);
  const [structureError, setStructureError] = useState<string | null>(null);

  const [selectedClass, setSelectedClass] = useState<OrgClassWithSubjects | null>(
    null
  );
  const [selectedSubject, setSelectedSubject] = useState<OrgNamedItem | null>(
    null
  );

  useEffect(() => {
    if (!token) {
      setStructureLoading(false);
      return;
    }
    let cancelled = false;
    setStructureLoading(true);
    setStructureError(null);
    getOrgStructure(token)
      .then((data) => {
        if (!cancelled) setStructure(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setStructureError(
            err instanceof Error ? err.message : "Failed to load organization data"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setStructureLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const waitingForUser = Boolean(token) && user == null;

  const assignedClassIds = user?.assigned_classes ?? [];
  const assignedSubjectIds = user?.assigned_subjects ?? [];

  const filteredClasses = useMemo(() => {
    if (!user) return [];
    return structure.classes.filter((c) => assignedClassIds.includes(c.id));
  }, [structure.classes, user, assignedClassIds]);

  const subjectsForSelectedClass = useMemo(() => {
    if (!selectedClass || !user) return [];
    return selectedClass.subjects.filter((s) =>
      assignedSubjectIds.includes(s.id)
    );
  }, [selectedClass, user, assignedSubjectIds]);

  const canTeachSomething = useMemo(() => {
    if (!user) return false;
    for (const c of filteredClasses) {
      if (c.subjects.some((s) => assignedSubjectIds.includes(s.id))) {
        return true;
      }
    }
    return false;
  }, [filteredClasses, assignedSubjectIds, user]);

  const noAssignableContext =
    Boolean(user) &&
    !structureLoading &&
    !structureError &&
    (filteredClasses.length === 0 || !canTeachSomething);

  const onClassChange = useCallback((id: string | null) => {
    if (!id) {
      setSelectedClass(null);
      setSelectedSubject(null);
      return;
    }
    const c = filteredClasses.find((x) => x.id === id);
    setSelectedClass(c ?? null);
    setSelectedSubject(null);
  }, [filteredClasses]);

  const handleSubjectChange = useCallback(
    (id: string | null) => {
      if (!id) {
        setSelectedSubject(null);
        return;
      }
      const s = subjectsForSelectedClass.find((x) => x.id === id);
      setSelectedSubject(s ?? null);
    },
    [subjectsForSelectedClass]
  );

  function workspaceHref() {
    if (!selectedClass || !selectedSubject) return "#";
    const q = new URLSearchParams({
      classId: selectedClass.id,
      subjectId: selectedSubject.id,
    });
    return `/teacher/workspace?${q.toString()}`;
  }

  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-6">
      <div className="flex w-full flex-col gap-6">
        <div className="w-full text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Teacher Panel
          </h1>
        </div>

        <h2 className="text-center text-lg font-semibold text-slate-900 dark:text-slate-50">
          Select your teaching context
        </h2>

        <Card className="w-full rounded-xl shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">Class &amp; subject</CardTitle>
            <CardDescription>
              Create structured curriculum from scratch or import from the admin
              catalog.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {waitingForUser ? (
              <p className="text-sm text-slate-500">Loading account…</p>
            ) : null}
            {structureLoading ? (
              <p className="text-sm text-slate-500">Loading organization data…</p>
            ) : null}
            {structureError ? (
              <p className="text-sm text-red-600 dark:text-red-400">
                {structureError}
              </p>
            ) : null}
            {noAssignableContext ? (
              <p className="text-sm text-amber-800 dark:text-amber-200">
                No classes/subjects assigned for your account. Contact your
                organization administrator.
              </p>
            ) : null}

            {!waitingForUser &&
            !structureLoading &&
            !structureError &&
            !noAssignableContext ? (
              <>
                <div className="flex flex-col gap-2">
                  <Label
                    htmlFor="teacher-class"
                    className="text-slate-700 dark:text-slate-300"
                  >
                    Class
                  </Label>
                  <select
                    id="teacher-class"
                    value={selectedClass?.id ?? ""}
                    onChange={(e) =>
                      onClassChange(e.target.value === "" ? null : e.target.value)
                    }
                    className={selectClassName}
                  >
                    <option value="">Choose…</option>
                    {filteredClasses.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                {selectedClass ? (
                  <div className="flex flex-col gap-2">
                    <Label
                      htmlFor="teacher-subject"
                      className="text-slate-700 dark:text-slate-300"
                    >
                      Subject
                    </Label>
                    <select
                      id="teacher-subject"
                      value={selectedSubject?.id ?? ""}
                      onChange={(e) =>
                        handleSubjectChange(
                          e.target.value === "" ? null : e.target.value
                        )
                      }
                      className={selectClassName}
                    >
                      <option value="">Choose…</option>
                      {subjectsForSelectedClass.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    {subjectsForSelectedClass.length === 0 ? (
                      <p className="text-xs text-amber-800 dark:text-amber-200">
                        No subjects for this class match your assignments.
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}

            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button
                type="button"
                className={cn(
                  "w-full sm:w-auto",
                  "disabled:cursor-not-allowed disabled:opacity-50"
                )}
                disabled={
                  waitingForUser ||
                  structureLoading ||
                  Boolean(structureError) ||
                  noAssignableContext ||
                  !selectedClass ||
                  !selectedSubject
                }
                onClick={() => {
                  if (!selectedClass || !selectedSubject) return;
                  router.push(workspaceHref());
                }}
              >
                Content workspace
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
