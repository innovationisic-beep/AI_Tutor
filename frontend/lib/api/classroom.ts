import type {
  ClassSessionInstance,
  ClassSessionPlan,
  PlanValidationResult,
  StudentPlanEnrollment,
} from "../types/classroom";

const API_BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000");

function authHeaders(token: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (j && typeof j.detail === "string") return j.detail;
    if (j?.detail?.errors) {
      return j.detail.errors.map((e: { message?: string }) => e.message ?? "").join("; ");
    }
    if (Array.isArray(j.detail))
      return j.detail.map((e: { msg?: string }) => e.msg ?? "").join(" ");
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function createClassSessionPlan(
  token: string,
  body: {
    teacher_topic_id: string;
    class_id: string;
    subject_id: string;
    sequence_number: number;
    title: string;
    description?: string;
    target_duration_minutes?: number | null;
    teacher_notes?: string;
  }
): Promise<ClassSessionPlan> {
  const res = await fetch(`${API_BASE}/classroom/plans`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function listClassSessionPlans(
  token: string,
  params: { teacher_topic_id: string; class_id: string; status?: string }
): Promise<ClassSessionPlan[]> {
  const q = new URLSearchParams({
    teacher_topic_id: params.teacher_topic_id,
    class_id: params.class_id,
  });
  if (params.status) q.set("status", params.status);
  const res = await fetch(`${API_BASE}/classroom/plans?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan[]>;
}

export async function getClassSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(`${API_BASE}/classroom/plans/${encodeURIComponent(planId)}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function updateClassSessionPlan(
  token: string,
  planId: string,
  body: {
    title?: string;
    description?: string;
    session_study_points?: string[];
    session_learning_outcomes?: string[];
    sequence_number?: number;
    target_duration_minutes?: number | null;
    teacher_notes?: string;
  }
): Promise<ClassSessionPlan> {
  const res = await fetch(`${API_BASE}/classroom/plans/${encodeURIComponent(planId)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function setClassSessionPlanItems(
  token: string,
  planId: string,
  items: {
    item_id?: string;
    sort_order: number;
    item_type: "zone_coverage" | "cluster_coverage" | "concept_coverage" | "non_curriculum";
    curriculum_zone_id?: string;
    curriculum_cluster_id?: string;
    curriculum_concept_id?: string;
    zone_number?: number;
    estimated_minutes?: number | null;
    is_required?: boolean;
    non_curriculum_label?: string;
  }[]
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/classroom/plans/${encodeURIComponent(planId)}/items`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({ items }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function validateClassSessionPlan(
  token: string,
  planId: string
): Promise<PlanValidationResult> {
  const res = await fetch(
    `${API_BASE}/classroom/plans/${encodeURIComponent(planId)}/validate`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<PlanValidationResult>;
}

export async function publishClassSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/classroom/plans/${encodeURIComponent(planId)}/publish`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function unpublishClassSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/classroom/plans/${encodeURIComponent(planId)}/unpublish`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function archiveClassSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/classroom/plans/${encodeURIComponent(planId)}/archive`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function createClassSessionInstance(
  token: string,
  body: {
    class_session_plan_id: string;
    scheduled_start: string;
    scheduled_end: string;
    timezone?: string;
  }
): Promise<ClassSessionInstance> {
  const res = await fetch(`${API_BASE}/classroom/instances`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionInstance>;
}

export async function listClassSessionInstances(
  token: string,
  params: { class_id: string; status?: string }
): Promise<ClassSessionInstance[]> {
  const q = new URLSearchParams({ class_id: params.class_id });
  if (params.status) q.set("status", params.status);
  const res = await fetch(`${API_BASE}/classroom/instances?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionInstance[]>;
}

export async function enrollWholeClass(
  token: string,
  instanceId: string
): Promise<StudentPlanEnrollment[]> {
  const res = await fetch(
    `${API_BASE}/classroom/instances/${encodeURIComponent(instanceId)}/enrollments`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ whole_class: true }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<StudentPlanEnrollment[]>;
}

export async function listInstanceEnrollments(
  token: string,
  instanceId: string
): Promise<StudentPlanEnrollment[]> {
  const res = await fetch(
    `${API_BASE}/classroom/instances/${encodeURIComponent(instanceId)}/enrollments`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<StudentPlanEnrollment[]>;
}

export async function startClassSessionInstance(
  token: string,
  instanceId: string
): Promise<ClassSessionInstance> {
  const res = await fetch(
    `${API_BASE}/classroom/instances/${encodeURIComponent(instanceId)}/start`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionInstance>;
}

export async function completeClassSessionInstance(
  token: string,
  instanceId: string
): Promise<ClassSessionInstance> {
  const res = await fetch(
    `${API_BASE}/classroom/instances/${encodeURIComponent(instanceId)}/complete`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionInstance>;
}
