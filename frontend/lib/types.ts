export type UserMe = {
  id: string;
  email: string;
  organization_id: string | null;
  role:
    | "admin"
    | "organization"
    | "teacher"
    | "student"
    | "parent";
  assigned_classes?: string[];
  assigned_subjects?: string[];
};

/** Tenant summary from login and GET /users/me */
export type OrganizationBrief = {
  id: string;
  name: string;
  organization_type: "personal" | "institution";
};

export type MeResponse = {
  user: UserMe;
  organization: OrganizationBrief | null;
  is_institution: boolean;
};

/** Tutor language preference. Presentation policy only — not a separate runtime. */
export type TutorLanguage = "en" | "hinglish";

/** GET /student/profile */
export type StudentProfile = {
  class_id: string | null;
  grade: string;
  preferred_language: TutorLanguage;
};

/** Institution row from GET /admin/organizations */
export type AdminOrgStatus = "active" | "inactive";
export type AdminOrgPlan = "free" | "basic" | "premium";

export type AdminOrganizationRow = {
  id: string;
  name: string;
  contact_email?: string | null;
  subscription_plan: AdminOrgPlan;
  status: AdminOrgStatus;
  max_students: number;
  max_teachers: number;
  invite_code: string | null;
  created_at: string;
};

export type AdminOrganizationCreated = AdminOrganizationRow & {
  invite_code: string;
  updated_at: string;
  /** Organization manager login (same as contact_email after create). */
  login_email: string;
};

export type AdminOrganizationDetail = AdminOrganizationRow & {
  updated_at: string;
  organization_type: string;
};

/** @deprecated use AdminOrganizationRow */
export type AdminOrganizationSummary = Pick<AdminOrganizationRow, "id" | "name">;

export type OrgNamedItem = {
  id: string;
  name: string;
  /** Linked curriculum Subject document id (Mongo ObjectId), when set by org admin */
  curriculum_subject_id?: string | null;
};

/** One org class with subjects nested under it. */
export type OrgClassWithSubjects = {
  id: string;
  name: string;
  subjects: OrgNamedItem[];
};

export type OrgStructure = {
  classes: OrgClassWithSubjects[];
};

/** Teacher user row for org admin (GET /org/teachers). */
export type OrgTeacher = {
  id: string;
  email: string;
  assigned_classes: string[];
  assigned_subjects: string[];
};

export type TeacherTopicRecord = {
  id: string;
  class_id: string;
  subject_id: string;
  topic_name: string;
  key_concepts: string[];
  /** Optional grouping of key_concepts into named clusters. null = auto-derive. */
  concept_clusters?: string[][] | null;
  /** Linked curriculum Topic id when teacher has mapped this row to CMS topic */
  curriculum_topic_id?: string | null;
};

/** GET /teacher/curriculum-preview */
export type TeacherCurriculumPreviewSampleNote = {
  concept?: string | null;
  content_markdown: string;
};

export type TeacherCurriculumPreviewSampleQuestion = {
  question_text: string;
  options: string[];
  correct_answer?: string | null;
};

export type TeacherCurriculumPreviewTopic = {
  name: string;
  concept_count: number;
  key_concepts: string[];
  sample_notes: TeacherCurriculumPreviewSampleNote[];
  sample_questions: TeacherCurriculumPreviewSampleQuestion[];
};

export type TeacherCurriculumPreview = {
  found: boolean;
  message?: string | null;
  subject?: { id: string; name: string; grade: string } | null;
  topics: TeacherCurriculumPreviewTopic[];
};

/** POST /teacher/import-curriculum */
export type TeacherImportCurriculumResult = {
  success: boolean;
  message?: string | null;
  imported_count: number;
  skipped_count: number;
};

/** Normalized note difficulty from API (legacy numeric coerced server-side). */
export type ContentDifficultyLevel = "basic" | "medium" | "hard";

/** GET /teacher/topic-notes */
export type TeacherTopicNoteItem = {
  id: string;
  topic_id: string;
  concept: string | null;
  concept_id?: string | null;
  concept_source?: string | null;
  content: string;
  note_type: string;
  difficulty_level: ContentDifficultyLevel;
  teaching_style: string | null;
  interest_category: string | null;
  created_at: string;
  updated_at: string;
};

/** GET /admin/catalog/subjects */
export type AdminCatalogSubject = {
  id: string;
  name: string;
  grade: string;
  board: string;
  description: string;
  academic_year: string;
  curriculum_version: string;
  status: string;
  is_active: boolean;
};

/** GET /admin/catalog/topics */
export type AdminCatalogTopic = {
  id: string;
  subject_id: string;
  topic_name: string;
  topic_slug: string;
  topic_description: string;
  key_concepts: string[];
  /** Optional grouping of key_concepts into named clusters. null = auto-derive. */
  concept_clusters?: string[][] | null;
  difficulty_level: string;
  default_depth: string;
  topic_order: number;
  estimated_time: number;
  status: string;
  is_active: boolean;
};

/** Structured curriculum (Phase 1) — zones / clusters / concepts */
export type CurriculumTopicSource = "catalog" | "teacher";

export type VtseStrategyId =
  | "hierarchy_concept_intro"
  | "clustered_trait_list"
  | "comparison_contrast"
  | "cycle_process"
  | "linear_process";

export type ConceptVtseTemplate = {
  strategy_id: VtseStrategyId | "";
  version?: number;
  payload: {
    left_label?: string;
    right_label?: string;
    rows?: Array<{
      dimension?: string;
      left?: string;
      right?: string;
      left_detail?: string;
      right_detail?: string;
      left_title?: string;
      right_title?: string;
    }>;
    steps?: Array<{
      label?: string;
      summary?: string;
      narration?: string;
      title?: string;
      annotation?: string;
    }>;
  };
};

export type VtseVisualBinding = {
  slot_kind: "step" | "trait" | "row" | "column";
  slot_key: string;
  slot_index: number;
  side: "" | "left" | "right" | "both";
};

export type VtseVisualRegion = {
  region_id: string;
  label?: string;
  teaching_purpose?: string;
  shape: "point" | "rect" | "ellipse" | "polygon";
  geometry: Record<string, unknown>;
  focus_point?: { x: number; y: number } | null;
  label_box?: { x: number; y: number; w: number; h: number } | null;
  highlight_color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
  bindings: VtseVisualBinding[];
};

export type VtseVisualAnchor = {
  anchor_id: string;
  label?: string;
  point: { x: number; y: number };
};

export type VtseVisualConnection = {
  connection_id: string;
  from_anchor: string;
  to_anchor: string;
  label?: string;
  teaching_purpose?: string;
  kind?: "flow" | "compare" | "generic";
  color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
  label_box?: { x: number; y: number; w: number; h: number } | null;
};

export type VtseVisualImage = {
  id: string;
  asset_key: string;
  storage_key: string;
  mime_type?: string;
  title?: string;
  teaching_purpose?: string;
  natural_width?: number;
  natural_height?: number;
  content_hash?: string;
  annotations_status?: "confirmed" | "stale";
  regions: VtseVisualRegion[];
  anchors?: VtseVisualAnchor[];
  connections?: VtseVisualConnection[];
};

export type VtseVisuals = {
  images: VtseVisualImage[];
};

export type CurriculumConcept = {
  id: string;
  curriculum_zone_id: string;
  curriculum_cluster_id: string;
  slug: string;
  display_name: string;
  canonical_runtime_key: string;
  sort_order: number;
  difficulty_level: string;
  estimated_learning_minutes: number | null;
  study_points?: string[];
  learning_outcomes?: string[];
  story_hook?: ConceptStoryHook | null;
  visual_teaching?: ConceptVisualTeachingPackage | null;
  teaching_sequence?: Array<"vtse" | "story_hook" | "visual_teaching" | "media">;
  teaching_sequence_mode?: "manual" | "auto" | string;
  teaching_sequence_auto?: Array<"vtse" | "story_hook" | "visual_teaching" | "media">;
  teaching_sequence_auto_reason?: string;
  teaching_sequence_auto_status?: "" | "resolved" | "fallback" | string;
  teaching_sequence_auto_stale?: boolean;
  vtse_template?: ConceptVtseTemplate | null;
  vtse_visuals?: VtseVisuals | null;
  status: string;
  published_revision: number;
};

/**
 * Story Hook supporting visual. `storage_key` is opaque and only round-tripped
 * by the authoring UI; the runtime addresses images by `asset_key`.
 */
export type ConceptStoryHookVisual = {
  id: string;
  asset_key: string;
  storage_key: string;
  description: string;
  teaching_purpose: string;
  mime_type: string;
  sort_order: number;
};

/** Authored Story Hook. `body` is the seed the planner builds from. */
export type ConceptStoryHook = {
  title: string;
  body: string;
  teacher_intent?: string;
  visuals?: ConceptStoryHookVisual[];
};

export type ConceptVisualTeachingRegion = {
  region_id: string;
  label: string;
  teaching_purpose: string;
  sort_order: number;
  shape: "point" | "rect" | "ellipse" | "polygon";
  geometry: Record<string, unknown>;
  focus_point?: { x: number; y: number } | null;
  label_box?: { x: number; y: number; w: number; h: number } | null;
  highlight_color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
};

export type ConceptVisualTeachingAnchor = {
  anchor_id: string;
  label: string;
  point: { x: number; y: number };
};

export type ConceptVisualTeachingConnection = {
  connection_id: string;
  from_anchor: string;
  to_anchor: string;
  label: string;
  teaching_purpose?: string;
  kind: "flow" | "compare" | "generic";
  color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
  label_box?: { x: number; y: number; w: number; h: number } | null;
};

export type ConceptVisualTeachingImage = {
  id: string;
  asset_key: string;
  storage_key: string;
  mime_type: string;
  sort_order: number;
  title: string;
  teaching_purpose: string;
  natural_width: number;
  natural_height: number;
  content_hash: string;
  annotations_status: "confirmed" | "stale";
  regions: ConceptVisualTeachingRegion[];
  anchors: ConceptVisualTeachingAnchor[];
  connections: ConceptVisualTeachingConnection[];
};

/** Authored Visual Teaching package on a curriculum concept. */
export type ConceptVisualTeachingPackage = {
  images: ConceptVisualTeachingImage[];
};

export type CurriculumCluster = {
  id: string;
  curriculum_zone_id: string;
  cluster_number: number;
  title: string;
  description?: string;
  study_points?: string[];
  learning_outcomes?: string[];
  sort_order: number;
  estimated_learning_minutes: number | null;
  status: string;
  concepts: CurriculumConcept[];
};

export type CurriculumZone = {
  id: string;
  zone_number: number;
  title: string;
  description: string;
  purpose: string;
  allows_vtse: boolean;
  is_system_zone: boolean;
  sort_order: number;
  status: string;
  clusters: CurriculumCluster[];
};

export type CurriculumTree = {
  topic_id: string;
  topic_source: CurriculumTopicSource;
  topic_name: string;
  curriculum_schema_version: string;
  curriculum_revision: number;
  curriculum_published_at: string | null;
  supports_class_sessions: boolean;
  zones: CurriculumZone[];
};

export type ConceptUsage = {
  concept_id: string;
  topic_id: string;
  topic_source: CurriculumTopicSource;
  canonical_runtime_key: string;
  display_name: string;
  note_count: number;
  question_count: number;
  notes: {
    id: string;
    note_type: string;
    concept_source: string | null;
    approved: boolean;
    content_markdown?: string;
    difficulty_level?: string;
  }[];
  questions: {
    id: string;
    concept_source: string | null;
    approved: boolean;
    question_text?: string;
    options?: string[];
    correct_answer?: string | null;
    explanation?: string;
    difficulty_level?: string;
    question_type?: "mcq" | "fill_in_blank" | "descriptive" | null;
    quiz_stage?: "concept_check" | "cluster_quiz" | null;
  }[];
  concept_check?: {
    mcq_count: number;
    mcq_cap: number;
    fill_in_blank_count: number;
    fill_in_blank_cap: number;
    slots_remaining: number;
  };
  cluster_quiz?: {
    used: number;
    cap: number;
    remaining: number;
    cluster_concept_ids: string[];
  };
};

export type CurriculumValidationIssue = {
  code: string;
  message: string;
  path: string;
};

export type CurriculumValidation = {
  errors: CurriculumValidationIssue[];
  warnings: CurriculumValidationIssue[];
  summary: Record<string, unknown>;
  ready_to_publish: boolean;
};

export type CurriculumPublishResult = {
  topic_id: string;
  topic_source: CurriculumTopicSource;
  curriculum_schema_version: string;
  curriculum_revision: number;
  curriculum_published_at: string | null;
  republished?: boolean;
  unpublished?: boolean;
};

/** Admin learning graph edges (global catalog) */
export type AdminPrerequisiteEdge = {
  id: string;
  topic_id: string;
  prerequisite_topic_id: string;
};

export type AdminProgressionEdge = {
  id: string;
  topic_id: string;
  recommended_next_topic_id: string;
  minimum_mastery_to_recommend: number;
};

export type Subject = {
  id: string;
  name: string;
  description: string;
  grade: string;
  board: string;
};

export type Topic = {
  id: string;
  topic_name: string;
  topic_description: string;
  difficulty_level: string;
  mastery_score: number | null;
};

export type DashboardData = {
  overall_mastery: number;
  topics_practiced: number;
  recent_topics: Topic[];
};

export type TutorActionButton = { id: string; label: string };

export type PedagogyIntroCardPayload = {
  kind: "session" | "cluster";
  heading: string;
  title: string;
  description?: string;
  study_points?: string[];
  learning_outcomes?: string[];
  /** @deprecated legacy field — use heading */
  subtitle?: string;
};

/**
 * Backend-owned Story Hook step protocol.
 *
 * The client never decides what comes next: it renders the step, and reports
 * that narration finished unless `awaiting` is true, in which case the student
 * answers in chat first.
 */
export type StoryHookStepMeta = {
  kind: "narration" | "visual" | "question" | "finish" | "reply";
  index: number;
  total: number;
  awaiting: boolean;
  last: boolean;
};

export type TutorVisual = {
  type: string;
  source?: string;
  data?: string;
  intent?: string;
  [key: string]: unknown;
};

/** GET /sessions/{id}/messages */
export type ChatHistoryMessage = {
  role: "user" | "assistant";
  content: string;
  message_type?: string | null;
  created_at: string;
  metadata_json?: string | null;
};

/** Optional teacher-progression hints from POST /sessions/ask or GET /sessions/active. */
export type TutorSessionMeta = {
  zone: number;
  cluster_index: number;
  total_clusters: number;
  concept_index: number;
  total_concepts: number;
  cluster_quiz_ready?: boolean;
  /** 1 = micro-teaching awaits student chat; client must not auto-send __action:quiz */
  micro_quiz_hold?: 0 | 1;
  /**
   * 1 = VTSE board finished but a post-VTSE Story Hook remains;
   * client sends __action:concept_vtse_stage_done after board TTS.
   */
  concept_teaching_await_vtse_done?: 0 | 1;
  /** Atomic VTSE opening ownership: unclaimed | starting | ready | failed */
  concept_vtse_opening_status?: string;
  /** Story Hook runtime: idle | playing | waiting_for_student | done | failed. */
  story_hook_status?: string;
  /** True while the Story Hook is waiting for the student to answer in chat. */
  story_hook_awaiting?: boolean;
  /** Visual Teaching runtime: idle | playing | done | failed. */
  visual_teaching_status?: string;
  /** Learner-facing micro question (from session.current_question) */
  micro_interaction_prompt?: string;
  /** True while post-concept student question loop is active. */
  student_questions_active?: boolean;
  /** Zone 1 — structured 3-question loop after main VTSE explanation. */
  concept_questions_active?: boolean;
  concept_question_index?: number;
  concept_question_followup?: boolean;
  concept_question_clarifying?: boolean;
  /** Brief pause after correct answer before next question appears */
  concept_question_pending_advance?: boolean;
  /** mcq | fill_in_blank — structured concept-check format */
  concept_question_type?: "mcq" | "fill_in_blank" | null;
  concept_question_options?: string[];
  /** Post-concept LLM study notes awaiting dismiss. */
  concept_notes_active?: boolean;
  concept_notes_concept?: string | null;
  concept_notes_markdown?: string | null;
  concept_notes_history?: Array<{ concept: string; markdown: string }>;
  /** True while a flow checkpoint gate is open (flow_vertical_process only). */
  flow_checkpoint_pending?: boolean;
  /** Completed step labels for the active flow checkpoint popup. */
  flow_checkpoint_step_labels?: string[];
  /** Learner-facing Concept Check / micro prompt (also mirrored from current_question). */
  current_question?: string;
  /** DEBUG ONLY — remove later */
  sus_score?: number;
  /** DEBUG ONLY — remove later */
  bloom_level?: "LOW" | "MEDIUM" | "HIGH";
  /** DEBUG ONLY — remove later */
  zone2_depth?: "shallow" | "medium" | "deep" | null;
  /** DEBUG ONLY — remove later */
  clarity_score?: number;
  /** Backend session.flow_state for resume (e.g. idle, explaining, quizzing). */
  flow_state?: string;
  /** Zone 1 — structured 3-question cluster quiz at cluster boundary. */
  cluster_quiz_active?: boolean;
  cluster_quiz_index?: number;
  cluster_quiz_followup?: boolean;
  cluster_quiz_clarifying?: boolean;
  cluster_quiz_pending_advance?: boolean;
  cluster_quiz_type?: "mcq" | "descriptive" | null;
  cluster_quiz_options?: string[];
  /** Cluster-end teachback (whiteboard panel). */
  cluster_teachback_active?: boolean;
  cluster_teachback_question?: string | null;
  cluster_teachback_phase?: "main" | "socratic" | "reteach_pending";
  /** True when the latest tutor reply belongs on the whiteboard (cluster teachback). */
  cluster_teachback_board?: boolean;
  /** True when the latest tutor reply belongs in the teachback panel (weak-score intro). */
  cluster_teachback_panel?: boolean;
  /** Cluster teachback done — zone transition Clarity Gate opens next. */
  zone_transition_gate_pending?: boolean;
  clarity_gate_active?: boolean;
};

/** Fields parsed from GET /sessions/active when present (teacher progression). */
export type ActiveSession = {
  id: string;
  topic_id: string;
  current_concept_index?: number;
  total_concepts?: number;
  current_concept?: string | null;
  current_zone?: number;
  flow_state?: string;
  meta?: TutorSessionMeta;
};

/** Normalized tutor response for UI (matches backend `type` + fields). */
export type TutorResponse = (
  | {
      type: "explanation";
      message: string;
      buttons?: TutorActionButton[];
      currentConcept?: string;
    }
  | {
      type: "quiz";
      message: string;
      question: string;
      questions?: Array<{ question: string; answer?: string; concept?: string }>;
      cluster_index?: number;
    }
  | {
      type: "feedback";
      message: string;
      correct: boolean;
      buttons?: TutorActionButton[];
      currentConcept?: string;
    }
  | {
      type: "concept_notes";
      message: string;
      conceptName?: string;
      currentConcept?: string;
    }
  | {
      type: "start";
      message: string;
      buttons: TutorActionButton[];
      currentConcept?: string;
    }
  | {
      type: "understanding_check";
      message: string;
      buttons: TutorActionButton[];
      currentConcept?: string;
    }
  | {
      type: "question_prompt";
      message: string;
      buttons?: TutorActionButton[];
    }
  | {
      type: "question_answered";
      message: string;
      buttons: TutorActionButton[];
    }
  | { type: "completed"; message: string }
  | {
      type: "root_cause";
      message: string;
      topic_id: string;
      buttons?: TutorActionButton[];
      currentConcept?: string;
    }
  | { type: "teachback"; message: string; current_concept?: string }
  | { type: "teachback_retry"; message: string; current_concept?: string }
  | { type: "teachback_passed"; message: string; current_concept?: string; zone_transition_gate_pending?: boolean }
  | { type: "teachback_exit"; message: string; current_concept?: string }
  | {
      type: "zone_2_entry_ready" | "zone_3_entry_ready" | "zone_4_entry_ready";
      message: string;
      currentConcept?: string;
      correct?: boolean;
    }
  | { type: "noop" }
  /** Visual Teaching sentence checkpoint ack — state-sync only, no flow change. */
  | {
      type: "visual_teaching_sentence_ack";
      scene_index?: number;
      beat_index?: number;
      sentence_index?: number;
      accepted?: boolean;
    }
  /** Visual Teaching advance reconcile ack (stale / already-advanced). */
  | {
      type: "visual_teaching_advance_ack";
      outcome?: "accepted" | "already_advanced" | "stale" | "completed";
      scene_index?: number;
      beat_index?: number;
      sentence_index?: number;
      status?: string;
      flow_state?: string;
    }
  /** VTSE opening ownership ack — never append a second timeline. */
  | {
      type: "vtse_opening_ack";
      outcome?: "claimed" | "already_starting" | "already_started" | "stale";
      concept_index?: number;
      status?: string;
      flow_state?: string;
    }
  | {
      type: "flow_checkpoint_clarification";
      message: string;
      outcome?: "stale";
    }
  /** Process VTSE checkpoint continue ack — pending cleared; timeline may resume. */
  | {
      type: "flow_checkpoint_continue_ack";
      outcome?: "accepted" | "already_cleared";
      flow_checkpoint_pending?: number;
    }
  /** Post-VTSE Concept Check arm — panel-only; never a board bubble. */
  | {
      type: "concept_question";
      message: string;
      /** Learner-facing stem (preferred over message when present). */
      question?: string;
      current_concept?: string;
      flow_state?: string;
    }
  | {
      type: "blocked";
      message: string;
      buttons?: TutorActionButton[];
      current_concept?: string;
    }
  /** Zone 0 — AI Anchoring (whiteboard, auto-advances after streaming) */
  | {
      type: "zone0_anchor";
      message: string;
      current_concept?: string;
      /** Dual-channel: omit / legacy = speech reveals as ink. */
      writing_mode?: "legacy" | "notes";
      display_text?: string;
      writes?: Array<{ sentence_index: number; text: string }>;
      visual?: TutorVisual | null;
    }
  /** Zone 0 — Prerequisite check question (shown as quiz card in chat) */
  | {
      type: "zone0_prereq";
      message: string;
      question?: string;
      current_concept?: string;
      writing_mode?: "legacy" | "notes";
      display_text?: string;
      writes?: Array<{ sentence_index: number; text: string }>;
      visual?: TutorVisual | null;
    }
  /** Zone 0 — Curiosity question (whiteboard, student engages or skips) */
  | {
      type: "zone0_curiosity";
      message: string;
      buttons?: TutorActionButton[];
      current_concept?: string;
      writing_mode?: "legacy" | "notes";
      display_text?: string;
      writes?: Array<{ sentence_index: number; text: string }>;
      visual?: TutorVisual | null;
    }
  /** Zone 0 — Anchor mirror / bridge (notes); auto-advances to Q2 */
  | {
      type: "zone0_mirror";
      message: string;
      current_concept?: string;
      writing_mode?: "legacy" | "notes";
      display_text?: string;
      writes?: Array<{ sentence_index: number; text: string }>;
      visual?: TutorVisual | null;
    }
  /** Pedagogy — session introduction card (whiteboard + TTS, before teaching) */
  | {
      type: "session_intro_card";
      message: string;
      pedagogy_card?: PedagogyIntroCardPayload;
      current_concept?: string;
    }
  /** Pedagogy — cluster introduction card (whiteboard + TTS, before teaching) */
  | {
      type: "cluster_intro_card";
      message: string;
      pedagogy_card?: PedagogyIntroCardPayload;
      current_concept?: string;
    }
  /** Concept teaching — AI-planned Story Hook stage, one step per turn */
  | {
      type: "concept_story_hook";
      message: string;
      story_hook_card?: {
        kind?: string;
        heading?: string;
        title: string;
        body?: string;
        description?: string;
        /** API-relative path to an authored visual; needs the API base prefix. */
        image_path?: string;
        image_alt?: string;
      };
      story_hook_step?: StoryHookStepMeta;
      current_concept?: string;
    }
  /** Concept teaching — Visual Teaching beat (diagram + synced overlays) */
  | {
      type: "concept_visual_teaching";
      message: string;
      current_concept?: string;
      visual?: TutorVisual | null;
    }
  /** Pedagogy — session recall question (session 2+) */
  | {
      type: "session_recall_prompt";
      message: string;
      current_concept?: string;
    }
  /** Pedagogy — session recall feedback + recap */
  | {
      type: "session_recall_feedback";
      message: string;
      current_concept?: string;
    }
  /** Pedagogy — cluster curiosity question */
  | {
      type: "cluster_curiosity_prompt";
      message: string;
      current_concept?: string;
    }
  /** Pedagogy — cluster curiosity appreciation */
  | {
      type: "cluster_curiosity_feedback";
      message: string;
      current_concept?: string;
      writing_mode?: "legacy" | "notes";
      display_text?: string;
      writes?: Array<{ sentence_index: number; text: string }>;
      visual?: TutorVisual | null;
    }
) & {
  meta?: TutorSessionMeta;
  visual?: TutorVisual;
  /** Timeline V3 board payload (authored VTSE → ITV3 product path). */
  instruction_timeline_v3?: Record<string, unknown> | null;
  planner_source?: string | null;
  timeline_metadata?: Record<string, unknown> | null;
};

/** POST /sessions/start when an in-progress session exists for the topic */
export type StartSessionResumePrompt = {
  type: "resume_prompt";
  message: string;
  buttons: string[];
  session_id: string;
};

export type SessionSummaryPayload = {
  summary_text: string;
  key_points_learned: string[];
  mistakes_identified: string[];
  strengths_identified: string[];
};

export type AssignmentBriefPayload = {
  id: string;
  difficulty_level: string;
  status: string;
  question_count: number;
  focus_concepts: string[];
};

/** Brief link to latest AI detailed note for the session topic (POST /sessions/end). */
export type DetailedNoteBriefPayload = {
  id: string;
  topic_id?: string | null;
};

/** Next-topic suggestion from recommendation service (session completion). */
export type RecommendedTopicPayload = {
  id: string;
  name: string;
  reason: string;
  score: number;
};

/** POST /sessions/end */
export type EndSessionResult = {
  status: string;
  session_id: string;
  summary: SessionSummaryPayload | null;
  assignment: AssignmentBriefPayload | null;
  detailed_notes_message: string | null;
  detailed_note: DetailedNoteBriefPayload | null;
  recommended_topics?: RecommendedTopicPayload[] | null;
};

/** Multi-session plan progression (Phase 3B.2). */
export type LearningPathSessionState =
  | "completed"
  | "active"
  | "available"
  | "locked";

export type LearningPathSessionRow = {
  session_plan_id: string;
  sequence_number: number;
  title: string;
  state: LearningPathSessionState;
};

export type PlanProgressionView = {
  learning_path: LearningPathSessionRow[];
  last_transition?: {
    kind?: string;
    title?: string;
    subtitle?: string;
    session_plan_id?: string;
    sequence_number?: number;
  } | null;
  completion_percentage: number;
  status: string;
  resume_pointer?: Record<string, unknown> | null;
  transition?: {
    session_complete?: boolean;
    unlock?: {
      unlocked_plan_id?: string | null;
      auto_start_plan_id?: string | null;
      title?: string | null;
      subtitle?: string | null;
    };
    auto_start?: {
      catalog_session_plan_id?: string | null;
      sequence_number?: number;
    };
  } | null;
};

export type AskQuestionApiBody = {
  answer: string;
  type?: string | null;
  question?: string | null;
  questions?: Array<{ question: string; answer?: string; concept?: string }> | null;
  cluster_index?: number | null;
  correct?: boolean | null;
  message?: string | null;
  root_topic_id?: string | null;
  current_concept?: string | null;
  /** Optional teacher-progression UI hints (zone, cluster, concept indices). */
  meta?: Record<string, unknown> | null;
  buttons?: TutorActionButton[] | null;
  visual?: TutorVisual | null;
  pedagogy_card?: Record<string, unknown> | null;
  orchestrator?: Record<string, unknown> | null;
  suggestion?: string | null;
  suggested_difficulty?: string | null;
  session_completion?: EndSessionResult | null;
  recommended_topics?: RecommendedTopicPayload[] | null;
  progression?: PlanProgressionView | null;
  /** Timeline V3 board payload (authored VTSE → ITV3 product path). */
  instruction_timeline_v3?: Record<string, unknown> | null;
  timeline_metadata?: Record<string, unknown> | null;
  planner_source?: string | null;
  /** Zone 0 dual-channel (non-question prose). */
  writing_mode?: "legacy" | "notes" | null;
  display_text?: string | null;
  /** Sentence-anchored board writes (validated sentence_index). */
  writes?: Array<{ sentence_index: number; text: string }> | null;
  story_hook_card?: Record<string, unknown> | null;
  story_hook_step?: StoryHookStepMeta | null;
  flow_state?: string | null;
  /** Explicit ack outcomes (VT advance, checkpoint continue, VTSE opening). */
  outcome?: string | null;
  flow_checkpoint_pending?: number | boolean | null;
};

/** GET /sessions/assignments (Beanie document shape, partial). */
export type StudentAssignment = {
  id: string;
  topic_id: string;
  session_id?: string | null;
  status: "pending" | "completed" | "cancelled" | string;
  difficulty_level: string;
  questions?: unknown[];
  focus_concepts?: string[];
  score?: number | null;
};

export type AssignmentQuestionStudentView = {
  source?: string | null;
  question_id?: string | null;
  question_text: string;
  difficulty_level?: number | null;
  evaluation?: {
    question_index: number;
    is_correct: boolean;
    student_answer: string;
    feedback: string;
  } | null;
};

/** GET /sessions/assignments/:id */
export type AssignmentDetail = {
  id: string;
  topic_id: string | null;
  topic_name: string | null;
  session_id: string | null;
  status: string;
  difficulty_level: string;
  score: number | null;
  focus_concepts: string[];
  questions: AssignmentQuestionStudentView[];
};

export type EvaluateAssignmentResult = {
  score: number;
  correct: number;
  total: number;
  results: Array<{
    question_index: number;
    is_correct: boolean;
    student_answer: string;
    feedback: string;
  }>;
};

/** GET /sessions/{session_id}/detailed-notes */
export type DetailedNotesResponse = {
  topic_id: string | null;
  content_markdown: string | null;
};

/** GET /sessions/detailed-notes */
export type DetailedNoteListItem = {
  id: string;
  topic_id: string;
  topic_name: string | null;
};

/** GET /sessions/detailed-notes/:id */
export type DetailedNoteDetail = {
  id: string;
  topic_id: string;
  topic_name: string | null;
  content_markdown: string;
};
