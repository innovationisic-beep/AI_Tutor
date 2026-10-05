"use client";

import type { CurriculumTopicSource, TeacherTopicRecord } from "@/lib/types";
import { V2CurriculumWorkflowNav } from "@/components/curriculum/V2CurriculumWorkflowNav";
import { TeacherLearningFlowPanel } from "./TeacherLearningFlowPanel";

type ContentEditorProps = {
  token: string | null;
  /** TeacherTopic id for learning flow */
  topicId: string | null;
  hasSelectedTopic: boolean;
  selectedTopic: TeacherTopicRecord | null;
  peerTopics: TeacherTopicRecord[];
  onToast: (message: string, variant?: "ok" | "err") => void;
  structuredCurriculumHref?: string | null;
  classroomPlanningHref?: string | null;
  curriculumTopicSource?: CurriculumTopicSource;
};

export function ContentEditor({
  token,
  topicId,
  hasSelectedTopic,
  selectedTopic,
  peerTopics,
  onToast,
  structuredCurriculumHref,
  classroomPlanningHref,
}: ContentEditorProps) {
  const topicMissing = !hasSelectedTopic || !topicId || !token;

  return (
    <div className="flex min-h-[320px] flex-col rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:min-h-[420px]">
      {structuredCurriculumHref ? (
        <V2CurriculumWorkflowNav
          className="mb-4"
          topicName={selectedTopic?.topic_name}
          builderHref={structuredCurriculumHref}
          planningHref={classroomPlanningHref}
          active="learningFlow"
        />
      ) : null}

      <p className="mb-3 text-xs font-medium text-slate-500 dark:text-slate-400">
        Learning flow — prerequisites and topic progression
      </p>

      {topicId && token && !topicMissing ? (
        <TeacherLearningFlowPanel
          token={token}
          teacherTopicId={topicId}
          peerTopics={peerTopics}
          onToast={onToast}
        />
      ) : (
        <p className="text-sm text-slate-500">
          Select a topic to edit prerequisites and progression.
        </p>
      )}
    </div>
  );
}
