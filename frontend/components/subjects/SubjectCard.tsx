"use client";

import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronRight } from "lucide-react";
import type { Subject } from "@/lib/types";

type Props = {
  subject: Subject;
};

export function SubjectCard({ subject }: Props) {
  return (
    <Link href={`/subjects/${subject.id}`} className="group block">
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-lg">{subject.name}</CardTitle>
            <ChevronRight className="size-5 shrink-0 text-slate-400 transition-transform group-hover:translate-x-0.5" />
          </div>
          {subject.description.trim() ? (
            <CardDescription className="line-clamp-3">
              {subject.description}
            </CardDescription>
          ) : null}
        </CardHeader>
        <CardContent>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {subject.grade === "—" && subject.board === "—"
              ? "Your class subject"
              : `Grade ${subject.grade} · ${subject.board}`}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}
