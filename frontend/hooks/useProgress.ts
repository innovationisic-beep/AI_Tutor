"use client";

import { useCallback, useState } from "react";
import {
  getDashboard,
  getOrgStructure,
  getStudentProfile,
  getStudentSubjectTopics,
  getSubjects,
  getTopics,
} from "@/lib/api";
import type { DashboardData, Subject, Topic } from "@/lib/types";

/** Match backend ``_normalize_grade_for_match`` for optional client-side filtering. */
function normalizeGradeForMatch(value: string | null | undefined): string {
  if (!value) return "";
  let s = value.trim().toLowerCase();
  if (s.startsWith("grade ")) s = s.slice(6).trim();
  return s;
}

export function useProgress(
  token: string | null,
  isInstitution: boolean
) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const d = await getDashboard(token);
      setDashboard({
        ...d,
        recent_topics: Array.isArray(d.recent_topics) ? d.recent_topics : [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [token]);

  const fetchSubjects = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      if (isInstitution) {
        const [structure, profile] = await Promise.all([
          getOrgStructure(token),
          getStudentProfile(token),
        ]);
        const classId = profile.class_id?.trim() || null;
        let cls = classId
          ? structure.classes.find((c) => c.id === classId)
          : undefined;
        if (classId && !cls && structure.classes.length > 0) {
          console.warn("Class ID mismatch, using fallback class", {
            classId,
            fallbackClassId: structure.classes[0]?.id,
          });
          cls = structure.classes[0];
        }
        const rows = cls?.subjects ?? [];
        setSubjects(
          rows.map((s) => ({
            id: s.id,
            name: s.name,
            description: "",
            grade: profile.grade?.trim() || "—",
            board: "—",
          }))
        );
      } else {
        const [list, profile] = await Promise.all([
          getSubjects(token),
          getStudentProfile(token).catch(() => null),
        ]);
        let subs: Subject[] = Array.isArray(list) ? list : [];
        const want = normalizeGradeForMatch(profile?.grade);
        if (want) {
          subs = subs.filter(
            (s) => normalizeGradeForMatch(s.grade) === want
          );
        }
        setSubjects(subs);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load subjects");
    } finally {
      setLoading(false);
    }
  }, [token, isInstitution]);

  const fetchTopicsForSubject = useCallback(
    async (subjectId: string): Promise<Topic[]> => {
      if (!token) throw new Error("Not authenticated");
      if (isInstitution) {
        const list = await getStudentSubjectTopics(token, subjectId);
        return Array.isArray(list) ? list : [];
      }
      const list = await getTopics(token, subjectId);
      return Array.isArray(list) ? list : [];
    },
    [token, isInstitution]
  );

  return {
    dashboard,
    subjects,
    loading,
    error,
    fetchDashboard,
    fetchSubjects,
    fetchTopicsForSubject,
  };
}
