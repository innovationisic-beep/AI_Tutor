"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { listDetailedNotes } from "@/lib/api";
import type { DetailedNoteListItem } from "@/lib/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function DetailedNotesPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<DetailedNoteListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let c = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await listDetailedNotes(token);
        if (!c) setItems(list);
      } catch (e) {
        if (!c)
          setError(
            e instanceof Error ? e.message : "Failed to load detailed notes"
          );
      } finally {
        if (!c) setLoading(false);
      }
    })();
    return () => {
      c = true;
    };
  }, [token]);

  return (
    <div className="w-full max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Detailed notes
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            AI-generated study notes for topics in your organization (reusable
            across sessions).
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/subjects">Subjects</Link>
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : null}
      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : null}

      {!loading && items.length === 0 && !error ? (
        <p className="text-sm text-slate-500">
          No detailed notes yet. They appear when the tutor saves approved AI
          notes for a topic (often after you end a session).
        </p>
      ) : null}

      <ul className="space-y-3">
        {items.map((n, index) => (
          <li key={`${n.id}-${index}`}>
            <Card className="transition hover:shadow-md">
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2 pb-2">
                <CardTitle className="text-base">
                  {n.topic_name ?? (
                    <>
                      Topic{" "}
                      <span className="font-mono text-xs text-slate-500">
                        {n.topic_id.length > 8
                          ? `…${n.topic_id.slice(-6)}`
                          : n.topic_id || "—"}
                      </span>
                    </>
                  )}
                </CardTitle>
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/detailed-notes/${encodeURIComponent(n.id)}`}>
                    Open
                  </Link>
                </Button>
              </CardHeader>
              <CardContent className="text-sm text-slate-600 dark:text-slate-400">
                {n.topic_name ? (
                  <p className="font-mono text-xs text-slate-500">
                    {n.topic_id.length > 8
                      ? `…${n.topic_id.slice(-6)}`
                      : n.topic_id}
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
