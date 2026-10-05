import type { ClassSessionPlan, PlanValidationResult } from "../types/classroom";

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
    if (j?.detail?.code) {
      return `${j.detail.code}: ${j.detail.message ?? ""}`.trim();
    }
    if (j?.detail?.errors) {
      return j.detail.errors.map((e: { message?: string }) => e.message ?? "").join("; ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function createCatalogSessionPlan(
  token: string,
  body: {
    catalog_topic_id: string;
    sequence_number: number;
    title: string;
    description?: string;
    target_duration_minutes?: number | null;
    teacher_notes?: string;
  }
): Promise<ClassSessionPlan> {
  const res = await fetch(`${API_BASE}/admin/catalog/classroom/plans`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function listCatalogSessionPlans(
  token: string,
  catalogTopicId: string,
  status?: string
): Promise<ClassSessionPlan[]> {
  const q = new URLSearchParams({ catalog_topic_id: catalogTopicId });
  if (status) q.set("status", status);
  const res = await fetch(`${API_BASE}/admin/catalog/classroom/plans?${q}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan[]>;
}

export async function setCatalogSessionPlanItems(
  token: string,
  planId: string,
  items: Parameters<typeof import("./classroom").setClassSessionPlanItems>[2]
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}/items`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify({ items }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function validateCatalogSessionPlan(
  token: string,
  planId: string
): Promise<PlanValidationResult> {
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}/validate`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<PlanValidationResult>;
}

export async function publishCatalogSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}/publish`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function unpublishCatalogSessionPlan(
  token: string,
  planId: string
): Promise<ClassSessionPlan> {
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}/unpublish`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export async function deleteCatalogSessionPlan(
  token: string,
  planId: string
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function updateCatalogSessionPlan(
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
  const res = await fetch(
    `${API_BASE}/admin/catalog/classroom/plans/${encodeURIComponent(planId)}`,
    {
      method: "PATCH",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<ClassSessionPlan>;
}

export type CatalogSessionPlanSummary = {
  id: string;
  sequence_number: number;
  title: string;
  description: string;
  target_duration_minutes?: number | null;
};

export async function listStudentCatalogSessionPlans(
  token: string,
  topicId: string
): Promise<CatalogSessionPlanSummary[]> {
  const res = await fetch(
    `${API_BASE}/curriculum/topics/${encodeURIComponent(topicId)}/session-plans`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CatalogSessionPlanSummary[]>;
}
