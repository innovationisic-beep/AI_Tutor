import type {
  AskQuestionApiBody,
  AssignmentDetail,
  ChatHistoryMessage,
  DetailedNoteDetail,
  DetailedNoteListItem,
  DetailedNotesResponse,
  DashboardData,
  EndSessionResult,
  EvaluateAssignmentResult,
  RecommendedTopicPayload,
  StartSessionResumePrompt,
  StudentAssignment,
  Subject,
  Topic,
  ActiveSession,
  TutorActionButton,
  TutorResponse,
  TutorSessionMeta,
  TutorVisual,
  UserMe,
  MeResponse,
  StudentProfile,
  TutorLanguage,
  OrganizationBrief,
  OrgNamedItem,
  OrgStructure,
  OrgTeacher,
  TeacherTopicRecord,
  TeacherCurriculumPreview,
  TeacherCurriculumPreviewTopic,
  TeacherImportCurriculumResult,
  TeacherTopicNoteItem,
  AdminOrganizationCreated,
  AdminOrganizationDetail,
  AdminOrganizationRow,
  AdminOrgPlan,
  AdminOrgStatus,
  AdminCatalogSubject,
  AdminCatalogTopic,
  AdminPrerequisiteEdge,
  AdminProgressionEdge,
} from "./types";

const API_BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000");

function authHeaders(token: string | null): HeadersInit {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function parseError(res: Response): Promise<string> {
  if (res.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("ai-tutor:auth-expired"));
  }
  try {
    const j = await res.json();
    if (j && typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail))
      return j.detail.map((e: { msg?: string }) => e.msg ?? "").join(" ");
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

/** FastAPI returns a JSON array; proxies or alternate APIs may wrap it. */
function parseSubjectList(raw: unknown): Subject[] {
  if (Array.isArray(raw)) return raw as Subject[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    for (const key of ["subjects", "data", "items", "results"]) {
      const v = o[key];
      if (Array.isArray(v)) return v as Subject[];
    }
  }
  return [];
}

function parseTopicList(raw: unknown): Topic[] {
  if (Array.isArray(raw)) return raw as Topic[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    for (const key of ["topics", "data", "items", "results"]) {
      const v = o[key];
      if (Array.isArray(v)) return v as Topic[];
    }
  }
  return [];
}

/** Avoid duplicate cards if a proxy merges responses with repeated ids. */
function dedupeById<T extends { id: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }
  return out;
}

/** Dashboard object or wrapped under `data` / `dashboard`. */
function parseDashboardPayload(raw: unknown): DashboardData {
  let root: unknown = raw;
  if (root && typeof root === "object" && !Array.isArray(root)) {
    const o = root as Record<string, unknown>;
    if (o.data && typeof o.data === "object" && !Array.isArray(o.data)) {
      root = o.data;
    } else if (
      o.dashboard &&
      typeof o.dashboard === "object" &&
      !Array.isArray(o.dashboard)
    ) {
      root = o.dashboard;
    }
  }
  if (!root || typeof root !== "object" || Array.isArray(root)) {
    return { overall_mastery: 0, topics_practiced: 0, recent_topics: [] };
  }
  const d = root as Record<string, unknown>;
  const recentRaw = d.recent_topics ?? d.topics ?? [];
  return {
    overall_mastery: Number(d.overall_mastery ?? 0),
    topics_practiced: Number(d.topics_practiced ?? 0),
    recent_topics: parseTopicList(recentRaw),
  };
}

function parseButtons(raw: AskQuestionApiBody): TutorActionButton[] | undefined {
  const b = raw.buttons;
  if (!Array.isArray(b)) return undefined;
  return b
    .map((x) => ({
      id: String((x as TutorActionButton).id ?? "").trim(),
      label: String((x as TutorActionButton).label ?? "").trim(),
    }))
    .filter((x) => x.id && x.label);
}

/** Coerce API meta numbers (JSON may send numeric fields as strings). */
function parseMetaFiniteNumber(raw: unknown): number | undefined {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim() !== "") {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

export function parseSessionMeta(raw: unknown): TutorSessionMeta | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  const zone = Number(o.zone);
  const cluster_index = Number(o.cluster_index);
  const total_clusters = Number(o.total_clusters);
  const concept_index = Number(o.concept_index);
  const total_concepts = Number(o.total_concepts);
  if (
    ![zone, cluster_index, total_clusters, concept_index, total_concepts].every(
      (n) => Number.isFinite(n)
    )
  ) {
    return undefined;
  }
  const out: TutorSessionMeta = {
    zone,
    cluster_index,
    total_clusters,
    concept_index,
    total_concepts,
  };
  const hold = o.micro_quiz_hold;
  if (hold === 0 || hold === 1) {
    out.micro_quiz_hold = hold;
  } else if (hold === true) {
    out.micro_quiz_hold = 1;
  } else if (hold === false) {
    out.micro_quiz_hold = 0;
  }
  const s = parseMetaFiniteNumber(o.sus_score);
  if (s !== undefined) {
    out.sus_score = s;
  }
  const b = o.bloom_level;
  if (b === "LOW" || b === "MEDIUM" || b === "HIGH") {
    out.bloom_level = b;
  }
  const z2d = o.zone2_depth;
  if (z2d === "shallow" || z2d === "medium" || z2d === "deep") {
    out.zone2_depth = z2d;
  } else if (z2d == null) {
    out.zone2_depth = null;
  }
  const cs = parseMetaFiniteNumber(o.clarity_score);
  if (cs !== undefined) {
    out.clarity_score = cs;
  }
  const sqa = o.student_questions_active;
  if (typeof sqa === "boolean") {
    out.student_questions_active = sqa;
  }
  const cqa = o.concept_questions_active;
  if (typeof cqa === "boolean") {
    out.concept_questions_active = cqa;
  }
  const cqi = parseMetaFiniteNumber(o.concept_question_index);
  if (cqi !== undefined) {
    out.concept_question_index = cqi;
  }
  if (typeof o.concept_question_followup === "boolean") {
    out.concept_question_followup = o.concept_question_followup;
  }
  if (typeof o.concept_question_clarifying === "boolean") {
    out.concept_question_clarifying = o.concept_question_clarifying;
  }
  if (typeof o.concept_question_pending_advance === "boolean") {
    out.concept_question_pending_advance = o.concept_question_pending_advance;
  }
  const cqt = o.concept_question_type;
  if (cqt === "mcq" || cqt === "fill_in_blank") {
    out.concept_question_type = cqt;
  }
  const cqopts = o.concept_question_options;
  if (Array.isArray(cqopts)) {
    out.concept_question_options = cqopts
      .map((x) => (typeof x === "string" ? x.trim() : ""))
      .filter(Boolean);
  }
  if (out.concept_question_type === "fill_in_blank") {
    out.concept_question_options = [];
  }
  if (typeof o.concept_notes_active === "boolean") {
    out.concept_notes_active = o.concept_notes_active;
  }
  const cnc = o.concept_notes_concept;
  if (typeof cnc === "string" && cnc.trim()) {
    out.concept_notes_concept = cnc.trim();
  }
  const cnm = o.concept_notes_markdown;
  if (typeof cnm === "string" && cnm.trim()) {
    out.concept_notes_markdown = cnm.trim();
  }
  const cnh = o.concept_notes_history;
  if (Array.isArray(cnh)) {
    const history = cnh
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const rec = item as Record<string, unknown>;
        const concept =
          typeof rec.concept === "string" ? rec.concept.trim() : "";
        const markdown =
          typeof rec.markdown === "string" ? rec.markdown.trim() : "";
        if (!concept || !markdown) return null;
        return { concept, markdown };
      })
      .filter((x): x is { concept: string; markdown: string } => x != null);
    if (history.length > 0) {
      out.concept_notes_history = history;
    }
  }
  const cqr = o.cluster_quiz_ready;
  if (typeof cqr === "boolean") {
    out.cluster_quiz_ready = cqr;
  }
  if (typeof o.cluster_quiz_active === "boolean") {
    out.cluster_quiz_active = o.cluster_quiz_active;
  }
  if (typeof o.cluster_quiz_index === "number") {
    out.cluster_quiz_index = o.cluster_quiz_index;
  }
  if (typeof o.cluster_quiz_followup === "boolean") {
    out.cluster_quiz_followup = o.cluster_quiz_followup;
  }
  if (typeof o.cluster_quiz_clarifying === "boolean") {
    out.cluster_quiz_clarifying = o.cluster_quiz_clarifying;
  }
  if (typeof o.cluster_quiz_pending_advance === "boolean") {
    out.cluster_quiz_pending_advance = o.cluster_quiz_pending_advance;
  }
  const clusterQuizType = o.cluster_quiz_type;
  if (clusterQuizType === "mcq" || clusterQuizType === "descriptive") {
    out.cluster_quiz_type = clusterQuizType;
  }
  const cqOpts = o.cluster_quiz_options;
  if (Array.isArray(cqOpts)) {
    out.cluster_quiz_options = cqOpts
      .map((x) => (typeof x === "string" ? x.trim() : ""))
      .filter(Boolean);
  }
  if (out.cluster_quiz_type === "descriptive") {
    out.cluster_quiz_options = [];
  }
  if (typeof o.cluster_teachback_active === "boolean") {
    out.cluster_teachback_active = o.cluster_teachback_active;
  }
  if (o.cluster_teachback_board === true) {
    out.cluster_teachback_board = true;
  }
  if (o.cluster_teachback_panel === true) {
    out.cluster_teachback_panel = true;
  }
  const ctPhase = o.cluster_teachback_phase;
  if (
    ctPhase === "main" ||
    ctPhase === "socratic" ||
    ctPhase === "reteach_pending"
  ) {
    out.cluster_teachback_phase = ctPhase;
  }
  const ctq = o.cluster_teachback_question;
  if (typeof ctq === "string" && ctq.trim()) {
    out.cluster_teachback_question = ctq.trim();
  }
  const mip = o.micro_interaction_prompt;
  if (typeof mip === "string" && mip.trim()) {
    out.micro_interaction_prompt = mip.trim();
  }
  const cqCur = o.current_question;
  if (typeof cqCur === "string" && cqCur.trim()) {
    out.current_question = cqCur.trim();
  }
  const fcp = o.flow_checkpoint_pending;
  if (fcp === true) {
    out.flow_checkpoint_pending = true;
  } else if (fcp === false) {
    out.flow_checkpoint_pending = false;
  }
  const fcsl = o.flow_checkpoint_step_labels;
  if (Array.isArray(fcsl)) {
    const labels = fcsl
      .map((x) => (typeof x === "string" ? x.trim() : ""))
      .filter(Boolean);
    if (labels.length > 0) {
      out.flow_checkpoint_step_labels = labels;
    }
  }
  const fs = o.flow_state;
  if (typeof fs === "string" && fs.trim()) {
    out.flow_state = fs.trim();
  }
  if (o.zone_transition_gate_pending === true) {
    out.zone_transition_gate_pending = true;
  } else if (o.zone_transition_gate_pending === false) {
    out.zone_transition_gate_pending = false;
  }
  if (o.clarity_gate_active === true) {
    out.clarity_gate_active = true;
  } else if (o.clarity_gate_active === false) {
    out.clarity_gate_active = false;
  }
  return out;
}

function metaFromAsk(raw: AskQuestionApiBody): { meta?: TutorSessionMeta } {
  const m = parseSessionMeta(raw.meta);
  return m ? { meta: m } : {};
}

/** Zone 0 dual-channel fields from ask body or nested visual. */
function zone0DualFromRaw(
  raw: AskQuestionApiBody,
  visual: TutorVisual | null
): {
  writing_mode?: "legacy" | "notes";
  display_text?: string;
  writes?: Array<{ sentence_index: number; text: string }>;
} {
  const fromVisualMode =
    visual && typeof visual.writing_mode === "string"
      ? visual.writing_mode.trim()
      : "";
  const fromRawMode =
    typeof raw.writing_mode === "string" ? raw.writing_mode.trim() : "";
  const mode = (fromRawMode || fromVisualMode).toLowerCase();
  const out: {
    writing_mode?: "legacy" | "notes";
    display_text?: string;
    writes?: Array<{ sentence_index: number; text: string }>;
  } = {};
  if (mode === "notes" || mode === "legacy") {
    out.writing_mode = mode;
  }
  if (typeof raw.display_text === "string") {
    out.display_text = raw.display_text;
  } else if (visual && typeof visual.display_text === "string") {
    out.display_text = visual.display_text;
  }
  const rawWrites = Array.isArray(raw.writes)
    ? raw.writes
    : visual && Array.isArray(visual.writes)
      ? visual.writes
      : null;
  if (rawWrites) {
    const writes: Array<{ sentence_index: number; text: string }> = [];
    for (const item of rawWrites) {
      if (!item || typeof item !== "object") continue;
      const rec = item as Record<string, unknown>;
      const idx = Number(rec.sentence_index);
      const text = typeof rec.text === "string" ? rec.text.trim() : "";
      if (!Number.isFinite(idx) || idx < 0 || !text) continue;
      writes.push({ sentence_index: Math.floor(idx), text });
    }
    if (writes.length) out.writes = writes;
  }
  return out;
}

export function normalizeTutorResponse(raw: AskQuestionApiBody): TutorResponse {
  const t = raw.type;
  const text = (raw.message || raw.answer || "").trim();
  const visual = raw.visual ?? null;
  const cc =
    raw.current_concept != null && String(raw.current_concept).trim() !== ""
      ? String(raw.current_concept).trim()
      : undefined;
  const buttons = parseButtons(raw);
  const mx = metaFromAsk(raw);
  // Timeline V3 board fields pass straight through unchanged.
  const itv3x: {
    instruction_timeline_v3?: Record<string, unknown>;
    planner_source?: string | null;
    timeline_metadata?: Record<string, unknown> | null;
  } = {};
  if (raw.instruction_timeline_v3 != null) {
    itv3x.instruction_timeline_v3 = raw.instruction_timeline_v3;
    itv3x.planner_source = raw.planner_source ?? null;
  }
  if (raw.timeline_metadata != null) {
    itv3x.timeline_metadata = raw.timeline_metadata;
  }
  // eslint-disable-next-line no-console
  console.info("[VTSE] api.ts itv3_present=", raw.instruction_timeline_v3 != null, "planner_source=", raw.planner_source ?? null);

  if (t === "quiz" && raw.question) {
    const q = String(raw.question).trim();
    const rawQuestions = raw.questions;
    const clusterBatch = Array.isArray(rawQuestions) && rawQuestions.length >= 2;
    if (clusterBatch) {
      const intro =
        (text || String(raw.message || "")).trim() ||
        "Let's put these ideas together.";
      return {
        type: "quiz",
        message: intro,
        question: q,
        questions: rawQuestions.map((item) => {
          const rec =
            item && typeof item === "object"
              ? (item as Record<string, unknown>)
              : {};
          return {
            question: String(rec.question ?? "").trim(),
            answer:
              rec.answer != null ? String(rec.answer).trim() : undefined,
            concept:
              rec.concept != null ? String(rec.concept).trim() : undefined,
          };
        }),
        cluster_index:
          typeof raw.cluster_index === "number" ? raw.cluster_index : undefined,
        ...(visual ? { visual } : {}),
        ...mx,
      };
    }
    const full = (raw.answer || "").trim();
    let intro = full;
    if (q && full.includes(q)) {
      intro = full.replace(q, "").replace(/\n+$/, "").trim();
    } else if (full.includes("\n\n")) {
      intro = full.split("\n\n")[0]?.trim() ?? full;
    }
    if (!intro) intro = "Let's try one to check your understanding.";
    return {
      type: "quiz",
      message: intro,
      question: q,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "feedback") {
    return {
      type: "feedback",
      message: text,
      correct: Boolean(raw.correct),
      buttons: buttons,
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "concept_notes") {
    const conceptName =
      raw.concept_name != null && String(raw.concept_name).trim() !== ""
        ? String(raw.concept_name).trim()
        : cc;
    return {
      type: "concept_notes",
      message: text || "",
      conceptName,
      currentConcept: cc ?? conceptName,
      ...mx,
    };
  }
  if (t === "start") {
    return {
      type: "start",
      message: text || "Ready to start this topic?",
      buttons: buttons ?? [],
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "understanding_check") {
    return {
      type: "understanding_check",
      message: text || "Do you understand or do you have a question?",
      buttons: buttons ?? [],
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "question_prompt") {
    return {
      type: "question_prompt",
      message: text || "What is your question?",
      buttons: buttons,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "question_answered") {
    return {
      type: "question_answered",
      message: text || "—",
      buttons: buttons ?? [],
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "completed") {
    return {
      type: "completed",
      message: text || "Great job! You completed this topic.",
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "root_cause") {
    const tid =
      raw.root_topic_id != null && String(raw.root_topic_id).trim() !== ""
        ? String(raw.root_topic_id).trim()
        : "";
    return {
      type: "root_cause",
      message: text || "Let's strengthen a foundation topic first.",
      topic_id: tid,
      buttons: buttons,
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  // Pass teachback types through unchanged so mapResponse can handle them.
  // Without these cases they fall through to the "explanation" default which
  // creates a board item and starts the onComplete → quiz-trigger loop.
  if (t === "teachback") {
    return { type: "teachback", message: text, current_concept: cc, ...mx };
  }
  if (t === "teachback_retry") {
    return { type: "teachback_retry", message: text, current_concept: cc, ...mx };
  }
  if (t === "teachback_exit") {
    return { type: "teachback_exit", message: text, current_concept: cc, ...mx };
  }
  if (t === "teachback_passed") {
    const gatePending = raw.zone_transition_gate_pending === true;
    return {
      type: "teachback_passed",
      message: text,
      current_concept: cc,
      ...(gatePending ? { zone_transition_gate_pending: true } : {}),
      ...mx,
    };
  }
  // Silent no-op from backend guards — must not create any board item.
  if (t === "noop") {
    return { type: "noop", ...mx };
  }
  if (t === "visual_teaching_sentence_ack") {
    return {
      type: "visual_teaching_sentence_ack",
      scene_index:
        typeof raw.scene_index === "number" ? raw.scene_index : undefined,
      beat_index:
        typeof raw.beat_index === "number" ? raw.beat_index : undefined,
      sentence_index:
        typeof raw.sentence_index === "number" ? raw.sentence_index : undefined,
      accepted: raw.accepted === true,
      ...mx,
    };
  }
  if (t === "visual_teaching_advance_ack") {
    const outcomeRaw = typeof raw.outcome === "string" ? raw.outcome : "";
    const outcome =
      outcomeRaw === "accepted" ||
      outcomeRaw === "already_advanced" ||
      outcomeRaw === "stale" ||
      outcomeRaw === "completed"
        ? outcomeRaw
        : undefined;
    return {
      type: "visual_teaching_advance_ack",
      outcome,
      scene_index:
        typeof raw.scene_index === "number" ? raw.scene_index : undefined,
      beat_index:
        typeof raw.beat_index === "number" ? raw.beat_index : undefined,
      sentence_index:
        typeof raw.sentence_index === "number" ? raw.sentence_index : undefined,
      status: typeof raw.status === "string" ? raw.status : undefined,
      flow_state:
        typeof raw.flow_state === "string" ? raw.flow_state : undefined,
      ...mx,
    };
  }
  if (t === "flow_checkpoint_clarification") {
    const outcome = raw.outcome === "stale" ? "stale" : undefined;
    return {
      type: "flow_checkpoint_clarification",
      message: outcome === "stale" ? "" : text || "Hope that clears your confusion.",
      ...(outcome ? { outcome } : {}),
      ...mx,
    };
  }
  if (t === "flow_checkpoint_continue_ack") {
    const outcomeRaw = String(raw.outcome ?? "").trim();
    const outcome =
      outcomeRaw === "accepted" || outcomeRaw === "already_cleared"
        ? outcomeRaw
        : undefined;
    return {
      type: "flow_checkpoint_continue_ack",
      outcome,
      flow_checkpoint_pending: Number(raw.flow_checkpoint_pending ?? 0) || 0,
      ...mx,
    };
  }
  if (t === "concept_question") {
    const q =
      (typeof raw.question === "string" && raw.question.trim()) ||
      text ||
      "";
    return {
      type: "concept_question",
      message: q || "Answer the question in the Concept Check panel.",
      question: q || undefined,
      current_concept: cc,
      flow_state:
        typeof raw.flow_state === "string" && raw.flow_state.trim()
          ? raw.flow_state.trim()
          : "concept_questions",
      ...mx,
    };
  }
  if (t === "cluster_check") {
    return {
      type: "explanation",
      message: text || "Now explain how these ideas work together",
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "clarity_gate_start") {
    return { type: "teachback", message: text, current_concept: cc, ...mx };
  }
  if (t === "clarity_gate_prompt") {
    return { type: "teachback_retry", message: text, current_concept: cc, ...mx };
  }
  if (t === "clarity_gate_passed") {
    return {
      type: "feedback",
      message: text || "Great work!",
      correct: true,
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (
    t === "zone_2_entry_ready" ||
    t === "zone_3_entry_ready" ||
    t === "zone_4_entry_ready"
  ) {
    return {
      type: t,
      message: text || `Zone entry ready.`,
      currentConcept: cc,
      correct: true,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (t === "clarity_gate_exit") {
    return {
      type: "explanation",
      message: text || "Let's keep going.",
      currentConcept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  // ── Zone 0 response types ────────────────────────────────────────────────
  if (t === "zone0_anchor") {
    return {
      type: "zone0_anchor",
      message: text || "—",
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...zone0DualFromRaw(raw, visual),
      ...mx,
    };
  }
  if (t === "zone0_prereq") {
    return {
      type: "zone0_prereq",
      message: text || "—",
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...zone0DualFromRaw(raw, visual),
      ...mx,
    };
  }
  if (t === "zone0_curiosity") {
    return {
      type: "zone0_curiosity",
      message: text || "—",
      buttons: buttons,
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...zone0DualFromRaw(raw, visual),
      ...mx,
    };
  }
  if (t === "zone0_mirror") {
    return {
      type: "zone0_mirror",
      message: text || "—",
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...zone0DualFromRaw(raw, visual),
      ...mx,
    };
  }
  if (t === "session_intro_card" || t === "cluster_intro_card") {
    const pedagogy_card =
      raw.pedagogy_card && typeof raw.pedagogy_card === "object"
        ? (raw.pedagogy_card as import("./types").PedagogyIntroCardPayload)
        : visual?.type === "pedagogy_intro" && visual.card
          ? (visual.card as import("./types").PedagogyIntroCardPayload)
          : undefined;
    return {
      type: t,
      message: text || "—",
      pedagogy_card,
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (
    t === "concept_story_hook" ||
    visual?.type === "concept_story_hook"
  ) {
    const story_hook_card =
      raw.story_hook_card && typeof raw.story_hook_card === "object"
        ? (raw.story_hook_card as {
            kind?: string;
            heading?: string;
            title: string;
            body?: string;
            description?: string;
            image_path?: string;
            image_alt?: string;
          })
        : visual?.type === "concept_story_hook" &&
            visual.card &&
            typeof visual.card === "object"
          ? (visual.card as {
              kind?: string;
              heading?: string;
              title: string;
              body?: string;
              description?: string;
              image_path?: string;
              image_alt?: string;
            })
          : undefined;
    return {
      type: "concept_story_hook" as const,
      message: text || "—",
      ...(story_hook_card ? { story_hook_card } : {}),
      ...(raw.story_hook_step
        ? {
            story_hook_step:
              raw.story_hook_step as import("./types").StoryHookStepMeta,
          }
        : {}),
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (
    t === "concept_visual_teaching" ||
    visual?.type === "concept_visual_teaching"
  ) {
    return {
      type: "concept_visual_teaching",
      message: text || "—",
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...mx,
    };
  }
  if (
    t === "session_recall_prompt" ||
    t === "session_recall_feedback" ||
    t === "cluster_curiosity_prompt" ||
    t === "cluster_curiosity_feedback"
  ) {
    return {
      type: t,
      message: text || "—",
      current_concept: cc,
      ...(visual ? { visual } : {}),
      ...(t === "cluster_curiosity_feedback"
        ? zone0DualFromRaw(raw, visual)
        : {}),
      ...mx,
    };
  }
  const timelineBeats =
    raw.instruction_timeline_v3 &&
    Array.isArray(
      (raw.instruction_timeline_v3 as { beats?: unknown }).beats
    )
      ? ((raw.instruction_timeline_v3 as { beats: unknown[] }).beats)
      : null;
  const msg = text || (timelineBeats && timelineBeats.length > 0 ? "" : "—");
  return {
    type: "explanation",
    message: msg,
    buttons: buttons,
    currentConcept: cc,
    ...(visual ? { visual } : {}),
    ...mx,
    ...itv3x,
  };
}

export type LoginResponse = {
  token: string;
  access_token: string;
  token_type?: string;
  user: UserMe;
  organization: OrganizationBrief | null;
  is_institution: boolean;
};

export async function login(
  email: string,
  password: string
): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: authHeaders(null),
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type TeachingStyle = "visual" | "practical" | "theory" | "mixed";

export type RegisterIndividualBody = {
  account_type: "individual";
  name: string;
  email: string;
  password: string;
  grade: string;
  interests?: string;
  preferred_teaching_style: TeachingStyle;
};

export type RegisterOrganizationBody = {
  account_type: "organization";
  name: string;
  email: string;
  password: string;
  invite_code: string;
  class_id: string;
};

export type RegisterBody = RegisterIndividualBody | RegisterOrganizationBody;

export async function register(body: RegisterBody): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: authHeaders(null),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type OrgByInviteResponse = {
  organization_name: string;
  classes: { id: string; name: string }[];
};

export async function getOrgByInviteCode(
  inviteCode: string
): Promise<OrgByInviteResponse> {
  const code = encodeURIComponent(inviteCode.trim().toUpperCase());
  const res = await fetch(`${API_BASE}/org/by-invite/${code}`, {
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as OrgByInviteResponse;
}

export async function getMe(token: string): Promise<MeResponse> {
  const res = await fetch(`${API_BASE}/users/me`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as MeResponse;
}

export async function getStudentProfile(token: string): Promise<StudentProfile> {
  const res = await fetch(`${API_BASE}/student/profile`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as StudentProfile;
}

export async function updateStudentProfile(
  token: string,
  patch: { preferred_language?: TutorLanguage }
): Promise<StudentProfile> {
  const res = await fetch(`${API_BASE}/student/profile`, {
    method: "PATCH",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as StudentProfile;
}

export async function getSubjects(token: string): Promise<Subject[]> {
  const res = await fetch(`${API_BASE}/curriculum/subjects`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const response = await res.json();
  return dedupeById(parseSubjectList(response));
}

export type CurriculumSubjectCatalogItem = { id: string; name: string };

export async function getCurriculumCatalogSubjects(
  token: string
): Promise<CurriculumSubjectCatalogItem[]> {
  const res = await fetch(`${API_BASE}/curriculum/subjects/catalog`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is Record<string, unknown> => x != null && typeof x === "object")
    .map((x) => ({
      id: String(x.id ?? ""),
      name: String(x.name ?? ""),
    }))
    .filter((x) => x.id);
}

export type CurriculumLinkApiResponse = {
  success: boolean;
  curriculum_subject_id: string | null;
};

export async function linkOrgSubjectToCurriculum(
  token: string,
  classId: string,
  subjectId: string,
  curriculumSubjectId: string | null
): Promise<CurriculumLinkApiResponse> {
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}/subject/${encodeURIComponent(subjectId)}/curriculum-link`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({
        curriculum_subject_id: curriculumSubjectId,
      }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const j = (await res.json()) as Record<string, unknown>;
  const cs = j.curriculum_subject_id;
  return {
    success: Boolean(j.success),
    curriculum_subject_id:
      cs != null && String(cs).trim() ? String(cs) : null,
  };
}

export async function getTopics(
  token: string,
  subjectId: string
): Promise<Topic[]> {
  const res = await fetch(
    `${API_BASE}/curriculum/subjects/${encodeURIComponent(subjectId)}/topics`,
    {
      headers: authHeaders(token),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const response = await res.json();
  return dedupeById(parseTopicList(response));
}

/**
 * Institution students: TeacherTopic-first topics. ``orgSubjectId`` is the organization
 * subject id (same as /subjects/[subjectId] in the app), not the curriculum catalog id.
 */
export async function getStudentSubjectTopics(
  token: string,
  orgSubjectId: string
): Promise<Topic[]> {
  const res = await fetch(
    `${API_BASE}/student/subjects/${encodeURIComponent(orgSubjectId)}/topics`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const response = await res.json();
  return dedupeById(parseTopicList(response));
}

export async function getDashboard(token: string): Promise<DashboardData> {
  const res = await fetch(`${API_BASE}/curriculum/dashboard`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const response = await res.json();
  return parseDashboardPayload(response);
}

export function parseActiveSessionPayload(raw: unknown): ActiveSession | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const idRaw = o.id ?? o._id;
  const topicRaw = o.topic_id;
  if (idRaw == null || topicRaw == null) return null;
  const idx = o.current_concept_index;
  const total = o.total_concepts;
  const zone = o.current_zone;
  const meta = parseSessionMeta(o.meta);
  const flowRaw = o.flow_state;
  const flow_state =
    typeof flowRaw === "string" && flowRaw.trim()
      ? flowRaw.trim()
      : meta?.flow_state;
  return {
    id: String(idRaw),
    topic_id: String(topicRaw),
    current_concept_index: typeof idx === "number" ? idx : undefined,
    total_concepts: typeof total === "number" ? total : undefined,
    current_concept:
      o.current_concept != null && String(o.current_concept).trim() !== ""
        ? String(o.current_concept)
        : undefined,
    current_zone: typeof zone === "number" && zone >= 0 ? zone : undefined,
    ...(flow_state ? { flow_state } : {}),
    ...(meta ? { meta } : {}),
  };
}

export async function getActiveSession(
  token: string,
  topicId: string
): Promise<ActiveSession | null> {
  const q = new URLSearchParams({ topic_id: topicId });
  const res = await fetch(`${API_BASE}/sessions/active?${q}`, {
    headers: authHeaders(token),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return parseActiveSessionPayload(raw);
}

export async function listSessionMessages(
  token: string,
  sessionId: string,
  limit = 200
): Promise<ChatHistoryMessage[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/messages?${q}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ChatHistoryMessage[];
}

export async function getSessionRestore(
  token: string,
  sessionId: string
): Promise<import("@/lib/sessionRestore").SessionRestorePayload> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/restore`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as import("@/lib/sessionRestore").SessionRestorePayload;
}

export async function saveBoardCheckpoint(
  token: string,
  sessionId: string,
  beatIndex: number,
  options?: { keepalive?: boolean; timelineId?: string }
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/board-checkpoint`,
    {
      method: "POST",
      keepalive: options?.keepalive === true,
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        beat_index: beatIndex,
        ...(options?.timelineId ? { timeline_id: options.timelineId } : {}),
      }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function saveStudentScratchpad(
  token: string,
  sessionId: string,
  content: string,
  options?: { keepalive?: boolean }
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/scratchpad`,
    {
      method: "PUT",
      keepalive: options?.keepalive === true,
      headers: {
        ...authHeaders(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

function isResumePrompt(raw: unknown): raw is StartSessionResumePrompt {
  if (!raw || typeof raw !== "object") return false;
  const o = raw as Record<string, unknown>;
  return o.type === "resume_prompt" && typeof o.session_id === "string";
}

/**
 * Institution sessions: use StudentProfile.class_id as curriculum_class_id and the
 * **organization subject id** (from /subjects/[subjectId]) as curriculum_subject_id — not the
 * curriculum catalog Subject ObjectId.
 */
export type StartSessionScope = {
  curriculum_class_id?: string | null;
  curriculum_subject_id?: string | null;
  catalog_session_plan_id?: string | null;
};

/** Coalesce concurrent identical start calls (e.g. React Strict Mode double mount). */
const startSessionInflight = new Map<
  string,
  Promise<{ id: string } | StartSessionResumePrompt>
>();

function startSessionDedupeKey(
  token: string,
  topicId: string,
  action?: "continue" | "restart",
  scope?: StartSessionScope
): string {
  const cc = scope?.curriculum_class_id?.trim() ?? "";
  const os = scope?.curriculum_subject_id?.trim() ?? "";
  const plan = scope?.catalog_session_plan_id?.trim() ?? "";
  const act = action ?? "";
  const t = token.length > 0 ? token.slice(0, 32) : "";
  return `${topicId}|${act}|${cc}|${os}|${plan}|${t}`;
}

export async function startSession(
  token: string,
  topicId: string,
  action?: "continue" | "restart",
  scope?: StartSessionScope
): Promise<{ id: string } | StartSessionResumePrompt> {
  const key = startSessionDedupeKey(token, topicId, action, scope);
  const existing = startSessionInflight.get(key);
  if (existing) return existing;

  const body: Record<string, unknown> = { topic_id: topicId };
  if (action) body.action = action;
  const cc = scope?.curriculum_class_id?.trim();
  const orgSubjectId = scope?.curriculum_subject_id?.trim();
  if (cc) body.curriculum_class_id = cc;
  if (orgSubjectId) body.curriculum_subject_id = orgSubjectId;
  const catalogPlanId = scope?.catalog_session_plan_id?.trim();
  if (catalogPlanId) body.catalog_session_plan_id = catalogPlanId;

  const promise = (async (): Promise<
    { id: string } | StartSessionResumePrompt
  > => {
    const res = await fetch(`${API_BASE}/sessions/start`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await parseError(res));
    const raw: unknown = await res.json();
    if (isResumePrompt(raw)) return raw;
    return raw as { id: string };
  })();

  startSessionInflight.set(key, promise);
  try {
    return await promise;
  } finally {
    startSessionInflight.delete(key);
  }
}

export type SendMessageResult = {
  tutor: TutorResponse;
  sessionCompletion: EndSessionResult | null;
  /** Mirrors AskQuestionResponse.recommended_topics (also on sessionCompletion). */
  recommendedTopics: RecommendedTopicPayload[] | null;
  progression: import("@/lib/types").PlanProgressionView | null;
};

function normalizeAssignmentRow(
  raw: Record<string, unknown>,
  index: number
): StudentAssignment {
  const idRaw = raw.id ?? raw._id;
  const id =
    idRaw != null && String(idRaw) !== ""
      ? String(idRaw)
      : `assignment-fallback-${index}`;
  return {
    id,
    topic_id:
      raw.topic_id != null && String(raw.topic_id) !== ""
        ? String(raw.topic_id)
        : "unknown",
    session_id:
      raw.session_id != null ? String(raw.session_id) : null,
    status: String(raw.status ?? "pending"),
    difficulty_level: String(raw.difficulty_level ?? "medium"),
    questions: Array.isArray(raw.questions) ? raw.questions : [],
    focus_concepts: Array.isArray(raw.focus_concepts)
      ? (raw.focus_concepts as string[])
      : [],
    score:
      typeof raw.score === "number"
        ? raw.score
        : raw.score == null
          ? null
          : Number(raw.score),
  };
}

export async function listAssignments(
  token: string
): Promise<StudentAssignment[]> {
  const res = await fetch(`${API_BASE}/sessions/assignments`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data: unknown = await res.json();
  if (!Array.isArray(data)) return [];
  return data.map((row, index) =>
    normalizeAssignmentRow(row as Record<string, unknown>, index)
  );
}

export async function getAssignmentDetail(
  token: string,
  assignmentId: string
): Promise<AssignmentDetail> {
  const res = await fetch(
    `${API_BASE}/sessions/assignments/${encodeURIComponent(assignmentId)}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AssignmentDetail;
}

export async function evaluateAssignment(
  token: string,
  assignmentId: string,
  answers: string[]
): Promise<EvaluateAssignmentResult> {
  const res = await fetch(`${API_BASE}/sessions/assignments/evaluate`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      assignment_id: assignmentId,
      answers,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as EvaluateAssignmentResult;
}

function normalizeDetailedNoteRow(
  raw: Record<string, unknown>,
  index: number
): DetailedNoteListItem {
  const idRaw = raw.id ?? raw._id;
  const id =
    idRaw != null && String(idRaw) !== ""
      ? String(idRaw)
      : `note-fallback-${index}`;
  return {
    id,
    topic_id:
      raw.topic_id != null && String(raw.topic_id) !== ""
        ? String(raw.topic_id)
        : "",
    topic_name:
      raw.topic_name != null && String(raw.topic_name) !== ""
        ? String(raw.topic_name)
        : null,
  };
}

export async function listDetailedNotes(
  token: string
): Promise<DetailedNoteListItem[]> {
  const res = await fetch(`${API_BASE}/sessions/detailed-notes`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data: unknown = await res.json();
  if (!Array.isArray(data)) return [];
  return data.map((row, index) =>
    normalizeDetailedNoteRow(row as Record<string, unknown>, index)
  );
}

export async function getDetailedNoteDetail(
  token: string,
  noteId: string
): Promise<DetailedNoteDetail> {
  const res = await fetch(
    `${API_BASE}/sessions/detailed-notes/${encodeURIComponent(noteId)}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as DetailedNoteDetail;
}

export async function getDetailedNotes(
  token: string,
  sessionId: string
): Promise<DetailedNotesResponse> {
  const res = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/detailed-notes`,
    {
      headers: authHeaders(token),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as DetailedNotesResponse;
}

export type CreateTopicNotePayload = {
  topic_id: string;
  concept?: string | null;
  concept_id?: string | null;
  structured?: boolean;
  content_markdown: string;
  note_type: string;
  difficulty_level: string;
  teaching_style?: string | null;
  interest_category?: string | null;
};

function normalizeContentDifficulty(
  raw: unknown
): "basic" | "medium" | "hard" {
  if (typeof raw === "number") {
    if (raw <= 1) return "basic";
    if (raw === 2) return "medium";
    return "hard";
  }
  const s = String(raw ?? "medium")
    .trim()
    .toLowerCase();
  if (s === "basic" || s === "medium" || s === "hard") return s;
  return "medium";
}

export async function createTopicNote(
  token: string,
  data: CreateTopicNotePayload
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/teacher/topic-note`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

function parseTeacherTopicNote(raw: unknown): TeacherTopicNoteItem | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const id = String(o.id ?? "");
  if (!id) return null;
  const nt = String(o.note_type ?? "detailed");
  return {
    id,
    topic_id: String(o.topic_id ?? ""),
    concept: o.concept == null ? null : String(o.concept),
    content: String(o.content ?? ""),
    note_type: nt === "summary" || nt === "revision" || nt === "detailed" ? nt : "detailed",
    difficulty_level: normalizeContentDifficulty(o.difficulty_level),
    teaching_style:
      o.teaching_style == null || String(o.teaching_style).trim() === ""
        ? null
        : String(o.teaching_style),
    interest_category:
      o.interest_category == null || String(o.interest_category).trim() === ""
        ? null
        : String(o.interest_category),
    created_at: String(o.created_at ?? ""),
    updated_at: String(o.updated_at ?? ""),
  };
}

export async function getTeacherTopicNotes(
  token: string,
  topicId: string,
  concept: string
): Promise<TeacherTopicNoteItem[]> {
  const q = new URLSearchParams({
    topic_id: topicId,
    concept: concept.trim(),
  });
  const res = await fetch(`${API_BASE}/teacher/topic-notes?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw
    .map((x) => parseTeacherTopicNote(x))
    .filter((x): x is TeacherTopicNoteItem => x != null);
}

export async function updateTeacherTopicNote(
  token: string,
  noteId: string,
  data: {
    content_markdown: string;
    note_type: string;
    difficulty_level: string;
    teaching_style?: string | null;
    interest_category?: string | null;
  }
): Promise<TeacherTopicNoteItem> {
  const res = await fetch(
    `${API_BASE}/teacher/topic-note/${encodeURIComponent(noteId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({
        content_markdown: data.content_markdown,
        note_type: data.note_type,
        difficulty_level: data.difficulty_level,
        teaching_style: data.teaching_style ?? null,
        interest_category: data.interest_category ?? null,
      }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const row = parseTeacherTopicNote(await res.json());
  if (!row) throw new Error("Invalid response");
  return row;
}

export async function deleteTeacherTopicNote(
  token: string,
  noteId: string
): Promise<{ success: boolean }> {
  const res = await fetch(
    `${API_BASE}/teacher/topic-note/${encodeURIComponent(noteId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ success: boolean }>;
}

export async function updateTeacherQuestion(
  token: string,
  questionId: string,
  data: {
    question_text: string;
    options: string[];
    correct_answer?: string | null;
    explanation: string;
    difficulty_level: string;
    question_type?: "mcq" | "fill_in_blank" | "descriptive" | null;
    quiz_stage?: "concept_check" | "cluster_quiz" | null;
    structured?: boolean;
  }
): Promise<{ id: string }> {
  const res = await fetch(
    `${API_BASE}/teacher/question/${encodeURIComponent(questionId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({
        question_text: data.question_text,
        options: data.options,
        correct_answer: data.correct_answer,
        explanation: data.explanation,
        difficulty_level: data.difficulty_level,
        question_type: data.question_type,
        quiz_stage: data.quiz_stage,
      }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw = (await res.json()) as { id?: string };
  return { id: String(raw.id ?? questionId) };
}

export async function deleteTeacherQuestion(
  token: string,
  questionId: string
): Promise<{ success: boolean }> {
  const res = await fetch(
    `${API_BASE}/teacher/question/${encodeURIComponent(questionId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ success: boolean }>;
}

export type CreateTeacherQuestionPayload = {
  topic_id: string;
  concept?: string | null;
  concept_id?: string | null;
  structured?: boolean;
  question_text: string;
  options: string[];
  correct_answer?: string | null;
  explanation: string;
  difficulty_level: string;
  question_type?: "mcq" | "fill_in_blank" | "descriptive" | null;
  quiz_stage?: "concept_check" | "cluster_quiz" | null;
};

export async function createQuestion(
  token: string,
  data: CreateTeacherQuestionPayload
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/teacher/question`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

function parseOrgStructure(raw: unknown): OrgStructure {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { classes: [] };
  }
  const o = raw as Record<string, unknown>;
  // Single source of truth: classes[].subjects[] only. Ignore any root-level
  // `subjects` if a proxy ever forwarded it — the API must not expose it.
  const classesRaw = Array.isArray(o.classes) ? o.classes : [];
  return {
    classes: classesRaw
      .filter((x): x is Record<string, unknown> => x != null && typeof x === "object")
      .map((x) => {
        const subs = Array.isArray(x.subjects) ? x.subjects : [];
        return {
          id: String(x.id ?? ""),
          name: String(x.name ?? ""),
          subjects: subs
            .filter((s): s is Record<string, unknown> => s != null && typeof s === "object")
            .map((s) => {
              const cs = s.curriculum_subject_id;
              return {
                id: String(s.id ?? ""),
                name: String(s.name ?? ""),
                curriculum_subject_id:
                  cs != null && String(cs).trim()
                    ? String(cs)
                    : null,
              };
            })
            .filter((s) => s.id),
        };
      })
      .filter((c) => c.id),
  };
}

export type OrgClassResponse = {
  id: string;
  name: string;
  subjects: OrgNamedItem[];
};

export async function createClass(
  token: string,
  name: string
): Promise<OrgClassResponse> {
  const res = await fetch(`${API_BASE}/org/class`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw = await res.json() as Record<string, unknown>;
  const subs = Array.isArray(raw.subjects) ? raw.subjects : [];
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    subjects: subs
      .filter((s): s is Record<string, unknown> => s != null && typeof s === "object")
      .map((s) => ({
        id: String(s.id ?? ""),
        name: String(s.name ?? ""),
      }))
      .filter((s) => s.id),
  };
}

export async function createSubject(
  token: string,
  classId: string,
  name: string
): Promise<OrgNamedItem> {
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}/subject`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ name }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw = await res.json() as Record<string, unknown>;
  const cs = raw.curriculum_subject_id;
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    curriculum_subject_id:
      cs != null && String(cs).trim() ? String(cs) : null,
  };
}

export async function updateOrgClass(
  token: string,
  classId: string,
  name: string
): Promise<OrgClassResponse> {
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({ name }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw = (await res.json()) as Record<string, unknown>;
  const subs = Array.isArray(raw.subjects) ? raw.subjects : [];
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    subjects: subs
      .filter((s): s is Record<string, unknown> => s != null && typeof s === "object")
      .map((s) => ({
        id: String(s.id ?? ""),
        name: String(s.name ?? ""),
      }))
      .filter((s) => s.id),
  };
}

export async function deleteOrgClass(
  token: string,
  classId: string,
  force = false
): Promise<void> {
  const q = force ? "?force=true" : "";
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}${q}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function updateOrgSubject(
  token: string,
  classId: string,
  subjectId: string,
  name: string
): Promise<OrgNamedItem> {
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}/subject/${encodeURIComponent(subjectId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({ name }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw = (await res.json()) as Record<string, unknown>;
  const cs = raw.curriculum_subject_id;
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    curriculum_subject_id:
      cs != null && String(cs).trim() ? String(cs) : null,
  };
}

export async function deleteOrgSubject(
  token: string,
  classId: string,
  subjectId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/org/class/${encodeURIComponent(classId)}/subject/${encodeURIComponent(subjectId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export type SuggestedCatalogTopic = {
  id: string;
  topic_name: string;
  key_concepts: string[];
};

export async function getSuggestedCatalogTopics(
  token: string,
  opts: { curriculum_subject_id?: string | null; subject_name?: string | null }
): Promise<SuggestedCatalogTopic[]> {
  const q = new URLSearchParams();
  const cs = opts.curriculum_subject_id?.trim();
  const sn = opts.subject_name?.trim();
  if (cs) q.set("curriculum_subject_id", cs);
  else if (sn) q.set("subject_name", sn);
  else throw new Error("Provide curriculum_subject_id or subject_name");
  const res = await fetch(
    `${API_BASE}/curriculum/suggested-catalog-topics?${q}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => {
    const o = x as Record<string, unknown>;
    const kc = o.key_concepts;
    return {
      id: String(o.id ?? ""),
      topic_name: String(o.topic_name ?? ""),
      key_concepts: Array.isArray(kc) ? kc.map((c) => String(c)) : [],
    };
  });
}

export async function getOrgStructure(token: string): Promise<OrgStructure> {
  const res = await fetch(`${API_BASE}/org/structure`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return parseOrgStructure(await res.json());
}

function parseConceptClusters(raw: unknown): string[][] | null {
  if (!Array.isArray(raw)) return null;
  const clusters = raw
    .filter(Array.isArray)
    .map((inner) => (inner as unknown[]).map((c) => String(c)).filter(Boolean));
  return clusters.length > 0 ? clusters : null;
}

function parseTeacherTopic(raw: unknown): TeacherTopicRecord | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const id = String(o.id ?? "");
  if (!id) return null;
  const kc = o.key_concepts;
  const ct = o.curriculum_topic_id;
  return {
    id,
    class_id: String(o.class_id ?? ""),
    subject_id: String(o.subject_id ?? ""),
    topic_name: String(o.topic_name ?? ""),
    key_concepts: Array.isArray(kc) ? kc.map((x) => String(x)) : [],
    concept_clusters: parseConceptClusters(o.concept_clusters),
    curriculum_topic_id:
      ct != null && String(ct).trim() ? String(ct) : null,
  };
}

export async function createTeacherTopic(
  token: string,
  data: {
    class_id: string;
    subject_id: string;
    topic_name: string;
    curriculum_topic_id?: string | null;
  }
): Promise<TeacherTopicRecord> {
  const payload: Record<string, unknown> = {
    class_id: data.class_id,
    subject_id: data.subject_id,
    topic_name: data.topic_name,
  };
  if (data.curriculum_topic_id?.trim()) {
    payload.curriculum_topic_id = data.curriculum_topic_id.trim();
  }
  const res = await fetch(`${API_BASE}/teacher/topic`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const row = parseTeacherTopic(await res.json());
  if (!row) throw new Error("Invalid response");
  return row;
}

export async function updateTeacherTopic(
  token: string,
  topicId: string,
  data: { topic_name: string }
): Promise<TeacherTopicRecord> {
  const res = await fetch(
    `${API_BASE}/teacher/topic/${encodeURIComponent(topicId)}`,
    {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify({ topic_name: data.topic_name.trim() }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const row = parseTeacherTopic(await res.json());
  if (!row) throw new Error("Invalid response");
  return row;
}

export async function deleteTeacherTopic(
  token: string,
  topicId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/teacher/topic/${encodeURIComponent(topicId)}`,
    {
      method: "DELETE",
      headers: authHeaders(token),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function linkTeacherTopicToCurriculum(
  token: string,
  teacherTopicId: string,
  curriculumTopicId: string
): Promise<TeacherTopicRecord> {
  const res = await fetch(
    `${API_BASE}/teacher/topic/${encodeURIComponent(teacherTopicId)}/link-curriculum`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({ curriculum_topic_id: curriculumTopicId }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const row = parseTeacherTopic(await res.json());
  if (!row) throw new Error("Invalid response");
  return row;
}

export async function addTeacherTopicConcepts(
  token: string,
  topicId: string,
  concepts: string[],
  concept_clusters?: string[][] | null
): Promise<TeacherTopicRecord> {
  const body: Record<string, unknown> = { concepts };
  if (concept_clusters !== undefined) {
    body.concept_clusters = concept_clusters;
  }
  const res = await fetch(
    `${API_BASE}/teacher/topic/${encodeURIComponent(topicId)}/concepts`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const row = parseTeacherTopic(await res.json());
  if (!row) throw new Error("Invalid response");
  return row;
}

export async function getTeacherTopics(
  token: string,
  classId: string,
  subjectId: string
): Promise<TeacherTopicRecord[]> {
  const q = new URLSearchParams({
    class_id: classId,
    subject_id: subjectId,
  });
  const res = await fetch(`${API_BASE}/teacher/topics?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw
    .map((x) => parseTeacherTopic(x))
    .filter((x): x is TeacherTopicRecord => x != null);
}

export async function getTeacherPrerequisites(
  token: string,
  topicId: string
): Promise<AdminPrerequisiteEdge[]> {
  const q = new URLSearchParams({ topic_id: topicId });
  const res = await fetch(`${API_BASE}/teacher/prerequisites?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminPrerequisiteEdge[]) : [];
}

export async function createTeacherPrerequisite(
  token: string,
  body: { topic_id: string; prerequisite_topic_id: string }
): Promise<AdminPrerequisiteEdge> {
  const res = await fetch(`${API_BASE}/teacher/prerequisite`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminPrerequisiteEdge;
}

export async function deleteTeacherPrerequisite(
  token: string,
  edgeId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/teacher/prerequisite/${encodeURIComponent(edgeId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getTeacherProgression(
  token: string,
  topicId: string
): Promise<AdminProgressionEdge[]> {
  const q = new URLSearchParams({ topic_id: topicId });
  const res = await fetch(`${API_BASE}/teacher/progression?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminProgressionEdge[]) : [];
}

export async function createTeacherProgression(
  token: string,
  body: {
    topic_id: string;
    recommended_next_topic_id: string;
    minimum_mastery_to_recommend: number;
  }
): Promise<AdminProgressionEdge> {
  const res = await fetch(`${API_BASE}/teacher/progression`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminProgressionEdge;
}

export async function deleteTeacherProgression(
  token: string,
  edgeId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/teacher/progression/${encodeURIComponent(edgeId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

function parseTeacherCurriculumPreview(raw: unknown): TeacherCurriculumPreview {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { found: false, message: "No curriculum found", topics: [] };
  }
  const o = raw as Record<string, unknown>;
  const found = Boolean(o.found);
  const sub = o.subject;
  let subject: TeacherCurriculumPreview["subject"];
  if (sub && typeof sub === "object" && !Array.isArray(sub)) {
    const s = sub as Record<string, unknown>;
    const id = String(s.id ?? "");
    if (id) {
      subject = {
        id,
        name: String(s.name ?? ""),
        grade: String(s.grade ?? ""),
      };
    }
  }
  const topicsRaw = o.topics;
  const topics: TeacherCurriculumPreview["topics"] = [];
  if (Array.isArray(topicsRaw)) {
    for (const t of topicsRaw) {
      if (!t || typeof t !== "object") continue;
      const tr = t as Record<string, unknown>;
      const kcRaw = tr.key_concepts;
      const key_concepts = Array.isArray(kcRaw)
        ? kcRaw.map((x) => String(x))
        : [];
      const snRaw = tr.sample_notes;
      const sample_notes: TeacherCurriculumPreviewTopic["sample_notes"] = [];
      if (Array.isArray(snRaw)) {
        for (const n of snRaw) {
          if (!n || typeof n !== "object") continue;
          const nr = n as Record<string, unknown>;
          sample_notes.push({
            concept:
              nr.concept != null && String(nr.concept).trim()
                ? String(nr.concept)
                : null,
            content_markdown: String(nr.content_markdown ?? ""),
          });
        }
      }
      const sqRaw = tr.sample_questions;
      const sample_questions: TeacherCurriculumPreviewTopic["sample_questions"] =
        [];
      if (Array.isArray(sqRaw)) {
        for (const q of sqRaw) {
          if (!q || typeof q !== "object") continue;
          const qr = q as Record<string, unknown>;
          const opts = qr.options;
          sample_questions.push({
            question_text: String(qr.question_text ?? ""),
            options: Array.isArray(opts)
              ? opts.map((x) => String(x))
              : [],
            correct_answer:
              qr.correct_answer != null && String(qr.correct_answer).trim()
                ? String(qr.correct_answer)
                : null,
          });
        }
      }
      topics.push({
        name: String(tr.name ?? ""),
        concept_count: Number(tr.concept_count ?? 0),
        key_concepts,
        sample_notes,
        sample_questions,
      });
    }
  }
  return {
    found,
    message: o.message != null ? String(o.message) : null,
    subject,
    topics,
  };
}

export async function getTeacherCurriculumPreview(
  token: string,
  classId: string,
  subjectId: string
): Promise<TeacherCurriculumPreview> {
  const q = new URLSearchParams({
    class_id: classId,
    subject_id: subjectId,
  });
  const res = await fetch(`${API_BASE}/teacher/curriculum-preview?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return parseTeacherCurriculumPreview(await res.json());
}

export async function importTeacherCurriculum(
  token: string,
  classId: string,
  subjectId: string
): Promise<TeacherImportCurriculumResult> {
  const res = await fetch(`${API_BASE}/teacher/import-curriculum`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      class_id: classId,
      subject_id: subjectId,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw = (await res.json()) as Record<string, unknown>;
  return {
    success: Boolean(raw.success ?? true),
    message: raw.message != null ? String(raw.message) : null,
    imported_count: Number(raw.imported_count ?? 0),
    skipped_count: Number(raw.skipped_count ?? 0),
  };
}

export type CreateOrgTeacherPayload = {
  email: string;
  password: string;
  assigned_classes: string[];
  assigned_subjects: string[];
};

export async function createTeacher(
  token: string,
  data: CreateOrgTeacherPayload
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/org/teacher`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listOrgTeachers(token: string): Promise<OrgTeacher[]> {
  const res = await fetch(`${API_BASE}/org/teachers`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => {
    const o = x as Record<string, unknown>;
    const ac = o.assigned_classes;
    const asu = o.assigned_subjects;
    return {
      id: String(o.id ?? ""),
      email: String(o.email ?? ""),
      assigned_classes: Array.isArray(ac) ? ac.map((id) => String(id)) : [],
      assigned_subjects: Array.isArray(asu) ? asu.map((id) => String(id)) : [],
    };
  });
}

export type UpdateOrgTeacherPayload = {
  email: string;
  assigned_classes: string[];
  assigned_subjects: string[];
};

export async function updateOrgTeacher(
  token: string,
  teacherId: string,
  data: UpdateOrgTeacherPayload
): Promise<OrgTeacher> {
  const res = await fetch(
    `${API_BASE}/org/teacher/${encodeURIComponent(teacherId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(data),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const o = (await res.json()) as Record<string, unknown>;
  const ac = o.assigned_classes;
  const asu = o.assigned_subjects;
  return {
    id: String(o.id ?? ""),
    email: String(o.email ?? ""),
    assigned_classes: Array.isArray(ac) ? ac.map((id) => String(id)) : [],
    assigned_subjects: Array.isArray(asu) ? asu.map((id) => String(id)) : [],
  };
}

export async function deleteOrgTeacher(
  token: string,
  teacherId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/org/teacher/${encodeURIComponent(teacherId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export type AssignOrgTeacherPayload = {
  user_id: string;
  assigned_classes: string[];
  assigned_subjects: string[];
};

export async function assignTeacher(
  token: string,
  data: AssignOrgTeacherPayload
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/org/assign`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type CreateOrganizationPayload = {
  name: string;
  email: string;
  password: string;
  max_students: number;
  max_teachers: number;
  subscription_plan: AdminOrgPlan;
  status: AdminOrgStatus;
};

export async function createOrganization(
  token: string,
  payload: CreateOrganizationPayload
): Promise<AdminOrganizationCreated> {
  const body = {
    name: payload.name.trim(),
    email: payload.email.trim(),
    password: payload.password,
    max_students: payload.max_students,
    max_teachers: payload.max_teachers,
    subscription_plan: payload.subscription_plan,
    status: payload.status,
  };
  const res = await fetch(`${API_BASE}/admin/organization`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminOrganizationCreated;
}

export async function listOrganizations(
  token: string
): Promise<AdminOrganizationRow[]> {
  const res = await fetch(`${API_BASE}/admin/organizations`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw as AdminOrganizationRow[];
}

export async function getAdminOrganization(
  token: string,
  organizationId: string
): Promise<AdminOrganizationDetail> {
  const res = await fetch(
    `${API_BASE}/admin/organization/${organizationId}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminOrganizationDetail;
}

export async function patchAdminOrganizationStatus(
  token: string,
  organizationId: string,
  status: AdminOrgStatus
): Promise<AdminOrganizationRow> {
  const res = await fetch(
    `${API_BASE}/admin/organization/${organizationId}`,
    {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify({ status }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminOrganizationRow;
}

// --- Global curriculum catalog (admin, organization_id null documents) ---

export async function getAdminCatalogSubjects(
  token: string
): Promise<AdminCatalogSubject[]> {
  const res = await fetch(`${API_BASE}/admin/catalog/subjects`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminCatalogSubject[]) : [];
}

export async function createAdminCatalogSubject(
  token: string,
  body: {
    name: string;
    grade: string;
    board?: string;
    description?: string;
    academic_year?: string;
    curriculum_version?: string;
  }
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/admin/subject`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      name: body.name.trim(),
      grade: body.grade.trim(),
      board: (body.board ?? "General").trim() || "General",
      description:
        (body.description?.trim() || "").length >= 10
          ? body.description!.trim()
          : "Curriculum subject — add a fuller description as needed.",
      academic_year: body.academic_year ?? "2024",
      curriculum_version: body.curriculum_version ?? "v1",
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function updateAdminCatalogSubject(
  token: string,
  subjectId: string,
  body: {
    name: string;
    grade: string;
    board?: string;
    description?: string;
    academic_year?: string;
    curriculum_version?: string;
    status?: string;
    is_active?: boolean;
  }
): Promise<{ id: string }> {
  const desc =
    (body.description?.trim() ||
      "Curriculum subject — add a fuller description as needed.") +
    "";
  const safeDesc =
    desc.length >= 10
      ? desc
      : "Curriculum subject — add a fuller description as needed.";
  const res = await fetch(
    `${API_BASE}/admin/subject/${encodeURIComponent(subjectId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({
        name: body.name.trim(),
        grade: body.grade.trim(),
        board: (body.board ?? "General").trim() || "General",
        description: safeDesc,
        academic_year: body.academic_year ?? "2024",
        curriculum_version: body.curriculum_version ?? "v1",
        status: body.status ?? "active",
        is_active: body.is_active ?? true,
      }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function deleteAdminCatalogSubject(
  token: string,
  subjectId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/subject/${encodeURIComponent(subjectId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getAdminCatalogTopics(
  token: string,
  subjectId: string
): Promise<AdminCatalogTopic[]> {
  const q = new URLSearchParams({ subject_id: subjectId });
  const res = await fetch(`${API_BASE}/admin/catalog/topics?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminCatalogTopic[]) : [];
}

export async function createAdminCatalogTopic(
  token: string,
  body: {
    subject_id: string;
    topic_name: string;
    topic_description: string;
    key_concepts?: string[];
    concept_clusters?: string[][] | null;
    difficulty_level: string;
    default_depth: string;
    topic_slug?: string;
    curriculum_version?: string;
  }
): Promise<{ id: string }> {
  const payload: Record<string, unknown> = {
    subject_id: body.subject_id,
    topic_name: body.topic_name.trim(),
    topic_description: body.topic_description.trim(),
    key_concepts: (body.key_concepts ?? []).map((c) => c.trim()).filter(Boolean),
    difficulty_level: body.difficulty_level,
    default_depth: body.default_depth,
    curriculum_version: body.curriculum_version ?? "v2",
  };
  if (body.concept_clusters !== undefined) {
    payload.concept_clusters = body.concept_clusters;
  }
  if (body.topic_slug?.trim()) payload.topic_slug = body.topic_slug.trim();
  const res = await fetch(`${API_BASE}/admin/topic`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function updateAdminCatalogTopic(
  token: string,
  topicId: string,
  body: {
    topic_name: string;
    topic_slug?: string | null;
    topic_description: string;
    key_concepts: string[];
    concept_clusters?: string[][] | null;
    difficulty_level: string;
    default_depth: string;
    topic_order?: number;
    estimated_time?: number;
    academic_year?: string;
    curriculum_version?: string;
    status?: string;
    is_active?: boolean;
  }
): Promise<{ id: string }> {
  const jsonBody: Record<string, unknown> = {
    topic_name: body.topic_name.trim(),
    topic_slug: body.topic_slug ?? null,
    topic_description: body.topic_description.trim(),
    key_concepts: body.key_concepts.map((c) => c.trim()).filter(Boolean),
    difficulty_level: body.difficulty_level,
    default_depth: body.default_depth,
    topic_order: body.topic_order ?? 0,
    estimated_time: body.estimated_time ?? 30,
    academic_year: body.academic_year ?? "2024",
    curriculum_version: body.curriculum_version ?? "v2",
    status: body.status ?? "active",
    is_active: body.is_active ?? true,
  };
  if (body.concept_clusters !== undefined) {
    jsonBody.concept_clusters = body.concept_clusters;
  }
  const res = await fetch(
    `${API_BASE}/admin/topic/${encodeURIComponent(topicId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(jsonBody),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function deleteAdminCatalogTopic(
  token: string,
  topicId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/topic/${encodeURIComponent(topicId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getAdminPrerequisites(
  token: string,
  topicId: string
): Promise<AdminPrerequisiteEdge[]> {
  const q = new URLSearchParams({ topic_id: topicId });
  const res = await fetch(`${API_BASE}/admin/prerequisites?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminPrerequisiteEdge[]) : [];
}

export async function createAdminPrerequisite(
  token: string,
  body: { topic_id: string; prerequisite_topic_id: string }
): Promise<AdminPrerequisiteEdge> {
  const res = await fetch(`${API_BASE}/admin/prerequisite`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminPrerequisiteEdge;
}

export async function deleteAdminPrerequisite(
  token: string,
  edgeId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/prerequisite/${encodeURIComponent(edgeId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getAdminProgression(
  token: string,
  topicId: string
): Promise<AdminProgressionEdge[]> {
  const q = new URLSearchParams({ topic_id: topicId });
  const res = await fetch(`${API_BASE}/admin/progression?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  return Array.isArray(raw) ? (raw as AdminProgressionEdge[]) : [];
}

export async function createAdminProgression(
  token: string,
  body: {
    topic_id: string;
    recommended_next_topic_id: string;
    minimum_mastery_to_recommend: number;
  }
): Promise<AdminProgressionEdge> {
  const res = await fetch(`${API_BASE}/admin/progression`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as AdminProgressionEdge;
}

export async function deleteAdminProgression(
  token: string,
  edgeId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/progression/${encodeURIComponent(edgeId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

/** conceptParam: omit key for all notes; "" for topic-wide only; else concept string */
export async function getAdminCatalogTopicNotes(
  token: string,
  topicId: string,
  conceptParam?: string
): Promise<TeacherTopicNoteItem[]> {
  const q = new URLSearchParams({ topic_id: topicId });
  if (conceptParam !== undefined) q.set("concept", conceptParam);
  const res = await fetch(`${API_BASE}/admin/catalog/topic-notes?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: unknown = await res.json();
  if (!Array.isArray(raw)) return [];
  return raw as TeacherTopicNoteItem[];
}

export async function createAdminTopicNote(
  token: string,
  body: {
    topic_id: string;
    concept?: string | null;
    concept_id?: string | null;
    structured?: boolean;
    content_markdown: string;
    note_type: "summary" | "detailed" | "revision";
    difficulty_level: string;
    teaching_style?: string | null;
    interest_category?: string | null;
  }
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/admin/topic-note`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function updateAdminTopicNote(
  token: string,
  noteId: string,
  body: {
    content_markdown: string;
    note_type: "summary" | "detailed" | "revision";
    difficulty_level: string;
    teaching_style?: string | null;
    interest_category?: string | null;
  }
): Promise<TeacherTopicNoteItem> {
  const res = await fetch(
    `${API_BASE}/admin/topic-note/${encodeURIComponent(noteId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TeacherTopicNoteItem;
}

export async function deleteAdminTopicNote(
  token: string,
  noteId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/topic-note/${encodeURIComponent(noteId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function createAdminQuestion(
  token: string,
  body: {
    topic_id: string;
    concept?: string | null;
    concept_id?: string | null;
    structured?: boolean;
    question_text: string;
    options: string[];
    correct_answer: string | null;
    explanation: string;
    difficulty_level: string;
    question_type?: "mcq" | "fill_in_blank" | "descriptive" | null;
    quiz_stage?: "concept_check" | "cluster_quiz" | null;
  }
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/admin/question`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { id: string };
}

export async function updateAdminQuestion(
  token: string,
  questionId: string,
  body: {
    question_text: string;
    options: string[];
    correct_answer: string | null;
    explanation: string;
    difficulty_level: string;
    question_type?: "mcq" | "fill_in_blank" | "descriptive" | null;
    quiz_stage?: "concept_check" | "cluster_quiz" | null;
    structured?: boolean;
  }
): Promise<{ id: string }> {
  const res = await fetch(
    `${API_BASE}/admin/question/${encodeURIComponent(questionId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const raw = (await res.json()) as { id?: string };
  return { id: String(raw.id ?? questionId) };
}

export async function deleteAdminQuestion(
  token: string,
  questionId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/question/${encodeURIComponent(questionId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function sendMessage(
  token: string,
  sessionId: string,
  message: string
): Promise<SendMessageResult> {
  const res = await fetch(`${API_BASE}/sessions/ask`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ session_id: sessionId, question: message }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const raw: AskQuestionApiBody = await res.json();
  const sessionCompletion =
    raw.session_completion != null
      ? (raw.session_completion as EndSessionResult)
      : null;
  return {
    tutor: normalizeTutorResponse(raw),
    sessionCompletion,
    recommendedTopics: raw.recommended_topics ?? null,
    progression: raw.progression ?? null,
  };
}

export type TtsSpeechStreamSession = {
  sessionId: string;
  ticket: string;
  streamPath: string;
  textChars: number;
  /** Absolute URL for HTMLAudioElement.src (ticket query included). */
  streamUrl: string;
};

/**
 * Authenticated prepare for progressive MP3 streaming.
 * Lemonfox credentials stay server-side; audio is fetched via one-time ticket URL.
 */
export async function prepareSpeechStream(
  token: string,
  text: string,
  options?: { signal?: AbortSignal },
): Promise<TtsSpeechStreamSession> {
  const res = await fetch(`${API_BASE}/tts/speech/sessions`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ text }),
    signal: options?.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as {
    session_id?: string;
    ticket?: string;
    stream_path?: string;
    text_chars?: number;
  };
  if (!data.session_id || !data.ticket || !data.stream_path) {
    throw new Error("TTS stream session response incomplete");
  }
  const streamUrl =
    `${API_BASE}${data.stream_path}?ticket=${encodeURIComponent(data.ticket)}`;
  return {
    sessionId: data.session_id,
    ticket: data.ticket,
    streamPath: data.stream_path,
    textChars: typeof data.text_chars === "number" ? data.text_chars : text.length,
    streamUrl,
  };
}

