"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play, RotateCcw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { launchClassSession, listStudentClassroomInstances } from "@/lib/api/studentClassroom";
import type { StudentClassroomInstance } from "@/lib/types/studentClassroom";
import { Button } from "@/components/ui/button";

export default function StudentClassroomPage() {
  const router = useRouter();
  const { token, ready, isAuthenticated } = useAuth();
  const [instances, setInstances] = useState<StudentClassroomInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [resumePrompt, setResumePrompt] = useState<{
    instanceId: string;
    topicId: string;
    sessionId: string;
    message: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await listStudentClassroomInstances(token);
      setInstances(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load classroom sessions");
      setInstances([]);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!ready) return;
    if (!isAuthenticated) return;
    void load();
  }, [ready, isAuthenticated, load]);

  async function handleLaunch(
    instance: StudentClassroomInstance,
    action?: "continue" | "restart"
  ) {
    if (!token) return;
    setBusyId(instance.id);
    setError(null);
    try {
      const out = await launchClassSession(token, instance.id, action);
      if (out.type === "resume_prompt" && out.session_id) {
        setResumePrompt({
          instanceId: instance.id,
          topicId: instance.teacher_topic_id,
          sessionId: out.session_id,
          message: out.message ?? "You have an ongoing session.",
        });
        return;
      }
      if (out.session_id) {
        router.push(
          `/learn/${instance.teacher_topic_id}?sessionId=${encodeURIComponent(out.session_id)}`
        );
        return;
      }
      setError("Launch did not return a session");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Launch failed");
    } finally {
      setBusyId(null);
    }
  }

  if (!ready || loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Loader2 className="mr-2 size-5 animate-spin" />
        Loading classroom sessions…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          Classroom sessions
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Scheduled and live sessions you are enrolled in.
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </div>
      ) : null}

      {resumePrompt ? (
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-900 dark:bg-violet-950/30">
          <p className="text-sm text-violet-950 dark:text-violet-100">{resumePrompt.message}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busyId === resumePrompt.instanceId}
              onClick={() => {
                setResumePrompt(null);
                router.push(
                  `/learn/${resumePrompt.topicId}?sessionId=${encodeURIComponent(resumePrompt.sessionId)}`
                );
              }}
            >
              Continue
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busyId === resumePrompt.instanceId}
              onClick={() => {
                const inst = instances.find((i) => i.id === resumePrompt.instanceId);
                setResumePrompt(null);
                if (inst) void handleLaunch(inst, "restart");
              }}
            >
              <RotateCcw className="mr-1 size-4" />
              Restart
            </Button>
          </div>
        </div>
      ) : null}

      {instances.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
          No classroom sessions scheduled. Your teacher will enroll you when a session is ready.
        </div>
      ) : (
        <ul className="space-y-3">
          {instances.map((instance) => (
            <li
              key={instance.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
            >
              <div>
                <p className="font-medium text-slate-900 dark:text-slate-50">
                  {instance.topic_name || "Topic"} — {instance.plan_title || "Session"}
                </p>
                <p className="text-xs text-slate-500">
                  #{instance.sequence_number} · {instance.status} ·{" "}
                  {new Date(instance.scheduled_start).toLocaleString()}
                </p>
              </div>
              <Button
                size="sm"
                disabled={
                  busyId === instance.id ||
                  instance.status === "completed" ||
                  instance.status === "cancelled"
                }
                onClick={() => void handleLaunch(instance)}
              >
                {busyId === instance.id ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <>
                    <Play className="mr-1 size-4" />
                    Launch
                  </>
                )}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
