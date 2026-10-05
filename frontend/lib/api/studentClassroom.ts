import type {
  LaunchClassSessionResponse,
  StudentClassroomInstance,
} from "../types/studentClassroom";

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
    if (j?.detail && typeof j.detail === "object" && "message" in j.detail) {
      return String((j.detail as { message?: string }).message ?? "Request failed");
    }
    if (Array.isArray(j.detail))
      return j.detail.map((e: { msg?: string }) => e.msg ?? "").join(" ");
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

export async function listStudentClassroomInstances(
  token: string,
  params?: { status?: string }
): Promise<StudentClassroomInstance[]> {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  const res = await fetch(`${API_BASE}/student/classroom/instances${suffix}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = (await res.json()) as { instances: StudentClassroomInstance[] };
  return data.instances ?? [];
}

export async function launchClassSession(
  token: string,
  instanceId: string,
  action?: "continue" | "restart"
): Promise<LaunchClassSessionResponse> {
  const res = await fetch(
    `${API_BASE}/student/classroom/instances/${encodeURIComponent(instanceId)}/launch`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ action: action ?? null }),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<LaunchClassSessionResponse>;
}
