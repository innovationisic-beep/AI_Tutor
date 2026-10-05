import type {
  ClassSessionPlanStatus,
  ClassSessionInstanceStatus,
  ClassSessionPlanItemType,
  ClassSessionPlanItem,
  ClassSessionPlan,
  PlanValidationResult,
  ClassSessionInstance,
  StudentPlanEnrollment,
} from "./classroom";

export type {
  ClassSessionPlanStatus,
  ClassSessionInstanceStatus,
  ClassSessionPlanItemType,
  ClassSessionPlanItem,
  ClassSessionPlan,
  PlanValidationResult,
  ClassSessionInstance,
  StudentPlanEnrollment,
};

export type StudentClassroomInstance = {
  id: string;
  class_session_plan_id: string;
  teacher_topic_id: string;
  topic_name: string;
  class_id: string;
  subject_id: string;
  scheduled_start: string;
  scheduled_end: string;
  timezone: string;
  status: ClassSessionInstanceStatus;
  plan_title: string;
  sequence_number: number;
};

export type LaunchClassSessionResponse = {
  type: "session" | "resume_prompt";
  session_id?: string | null;
  message?: string | null;
  buttons?: string[] | null;
  manifest_summary?: {
    key_count: number;
    cluster_count: number;
    first_concept?: string | null;
    launch_context: Record<string, unknown>;
  } | null;
};
