"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { getDetailedNoteDetail } from "@/lib/api";
import type { DetailedNoteDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DetailedNoteDetailPage() {
  const params = useParams();
  const noteId = params.noteId as string;
  const { token } = useAuth();
  const [detail, setDetail] = useState<DetailedNoteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !noteId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await getDetailedNoteDetail(token, noteId);
      setDetail(d);
    } catch (e) {
      setDetail(null);
      setError(
        e instanceof Error ? e.message : "Could not load detailed notes."
      );
    } finally {
      setLoading(false);
    }
  }, [token, noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !detail) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-8">
        <p className="text-sm text-slate-500">Loading notes…</p>
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 px-4 py-8">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        <Button variant="outline" asChild>
          <Link href="/detailed-notes">Back to detailed notes</Link>
        </Button>
      </div>
    );
  }

  if (!detail) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/detailed-notes">← Detailed notes</Link>
        </Button>
      </div>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {detail.topic_name ?? "Detailed notes"}
        </h1>
        {detail.topic_name ? (
          <p className="mt-1 font-mono text-xs text-slate-500">
            {detail.topic_id.length > 8
              ? `…${detail.topic_id.slice(-6)}`
              : detail.topic_id}
          </p>
        ) : null}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-500">
            Content
          </CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800 dark:text-slate-200">
            {detail.content_markdown || "—"}
          </pre>
        </CardContent>
      </Card>

      <Button variant="outline" asChild>
        <Link href="/detailed-notes">Back to detailed notes</Link>
      </Button>
    </div>
  );
}
