export type ClassSessionPlanStatus = "draft" | "published" | "archived";
export type ClassSessionInstanceStatus =
  | "scheduled"
  | "live"
  | "completed"
  | "cancelled";
export type ClassSessionPlanItemType =
  | "zone_coverage"
  | "cluster_coverage"
  | "concept_coverage"
  | "non_curriculum";
export type EnrollmentStatus = "enrolled" | "excused" | "withdrawn";

export type ClassSessionPlanItem = {
  item_id: string;
  sort_order: number;
  item_type: ClassSessionPlanItemType;
  curriculum_zone_id: string | null;
  curriculum_cluster_id: string | null;
  curriculum_concept_id: string | null;
  zone_number: number | null;
  canonical_runtime_key_snapshot: string | null;
  display_name_snapshot: string | null;
  estimated_minutes: number | null;
  is_required: boolean;
  non_curriculum_label: string | null;
};

export type ClassSessionPlan = {
  id: string;
  teacher_topic_id: string;
  class_id: string;
  subject_id: string;
  sequence_number: number;
  title: string;
  description: string;
  session_study_points?: string[];
  session_learning_outcomes?: string[];
  target_duration_minutes: number | null;
  teacher_notes: string;
  curriculum_schema_version: string;
  curriculum_revision: number;
  status: ClassSessionPlanStatus;
  published_at: string | null;
  items: ClassSessionPlanItem[];
};

export type PlanValidationResult = {
  errors: { code: string; message: string; path: string }[];
  warnings: { code: string; message: string; path: string }[];
  summary: Record<string, unknown>;
  ready_to_publish: boolean;
};

export type ClassSessionInstance = {
  id: string;
  class_session_plan_id: string;
  teacher_topic_id: string;
  class_id: string;
  subject_id: string;
  primary_teacher_id: string;
  scheduled_start: string;
  scheduled_end: string;
  timezone: string;
  status: ClassSessionInstanceStatus;
  enrollment_count: number;
  plan_snapshot: {
    plan_id: string;
    title: string;
    sequence_number: number;
    curriculum_revision: number;
    items: ClassSessionPlanItem[];
  };
};

export type StudentPlanEnrollment = {
  id: string;
  class_session_instance_id: string;
  student_id: string;
  enrollment_status: EnrollmentStatus;
  enrolled_at: string;
};
