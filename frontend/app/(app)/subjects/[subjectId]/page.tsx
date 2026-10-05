"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useProgress } from "@/hooks/useProgress";
import { TopicCard } from "@/components/subjects/TopicCard";
import type { Topic } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export default function SubjectTopicsPage() {
  const params = useParams();
  const router = useRouter();
  const subjectId = params.subjectId as string;
  const { token, isInstitution } = useAuth();
  const { fetchTopicsForSubject } = useProgress(token, isInstitution);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !subjectId) return;
    setLoading(true);
    setError(null);
    try {
      const list = await fetchTopicsForSubject(subjectId);
      setTopics(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load topics");
    } finally {
      setLoading(false);
    }
  }, [token, subjectId, fetchTopicsForSubject]);

  useEffect(() => {
    void load();
  }, [load]);

  function onTopicSelect(topicId: string) {
    if (!token) return;
    setStarting(topicId);
    const topic = topics.find((t) => t.id === topicId);
    const sp = new URLSearchParams({ subjectId });
    if (topic?.topic_name?.trim()) {
      sp.set("topicName", topic.topic_name.trim());
    }
    router.push(`/learn/${topicId}?${sp.toString()}`);
  }

  return (
    <div className="w-full max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/subjects">
            <ArrowLeft className="size-4" />
            Subjects
          </Link>
        </Button>
      </div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Topics</h1>
        <p className="mt-1 text-slate-600 dark:text-slate-400">
          Select a topic to start an AI tutor session.
        </p>
        {!loading && (
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-500">
            Showing {topics.length} topic
            {topics.length === 1 ? "" : "s"} from the API (same data as in your database for
            this subject).
          </p>
        )}
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">Loading topics…</p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        {topics.map((t) => (
          <TopicCard
            key={t.id}
            topic={t}
            disabled={starting !== null}
            onSelect={() => void onTopicSelect(t.id)}
          />
        ))}
      </div>

      {starting ? (
        <p className="text-sm text-slate-500">Starting session…</p>
      ) : null}

      {!loading && topics.length === 0 && !error ? (
        <p className="text-sm text-slate-500">No topics in this subject.</p>
      ) : null}
    </div>
  );
}
