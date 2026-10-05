"use client";

import { useRouter } from "next/navigation";
import type { RecommendedTopicPayload } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CHAT_META_TEXT_CLASS, CHAT_TEXT_CLASS } from "@/lib/teachingTypography";

type RecommendedTopicsProps = {
  topics: RecommendedTopicPayload[];
  /** Preserves e.g. `?subjectId=` when opening another topic from the same subject. */
  learnUrlSuffix?: string;
};

export function RecommendedTopics({
  topics,
  learnUrlSuffix = "",
}: RecommendedTopicsProps) {
  const router = useRouter();

  if (!topics.length) return null;

  return (
    <section className="w-full max-w-3xl space-y-3 px-1" aria-label="What to learn next">
      <h2 className={`text-slate-800 dark:text-slate-100 ${CHAT_TEXT_CLASS}`}>
        What to learn next
      </h2>
      <div className="flex flex-col gap-3">
        {topics.map((topic) => (
          <Card
            key={topic.id}
            className="rounded-xl border-slate-200/80 shadow-sm dark:border-slate-800"
          >
            <CardHeader className="space-y-1 pb-2">
              <CardTitle className={`leading-snug ${CHAT_TEXT_CLASS}`}>
                {topic.name || "Topic"}
              </CardTitle>
              <CardDescription className={`text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
                {topic.reason}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <Button
                type="button"
                size="sm"
                className="w-full sm:w-auto"
                onClick={() =>
                  router.push(`/learn/${topic.id}${learnUrlSuffix}`)
                }
              >
                Start learning
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

type RootTopicStudyFirstCardProps = {
  topicId: string;
  learnUrlSuffix?: string;
};

/** Shown under an assistant message when the tutor suggests a prerequisite topic. */
export function RootTopicStudyFirstCard({
  topicId,
  learnUrlSuffix = "",
}: RootTopicStudyFirstCardProps) {
  const router = useRouter();
  if (!topicId.trim()) return null;

  return (
    <Card className="max-w-[min(100%,42rem)] rounded-xl border-slate-200/80 shadow-sm dark:border-slate-800">
      <CardHeader className="space-y-1 pb-2">
        <CardTitle className={CHAT_TEXT_CLASS}>
          Recommended to study first
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 pt-0 sm:flex-row sm:items-center sm:justify-between">
        <p className={`text-slate-600 dark:text-slate-400 ${CHAT_META_TEXT_CLASS}`}>
          Open this topic to build the foundation before continuing.
        </p>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="shrink-0"
          onClick={() =>
            router.push(`/learn/${topicId.trim()}${learnUrlSuffix}`)
          }
        >
          Go to topic
        </Button>
      </CardContent>
    </Card>
  );
}
