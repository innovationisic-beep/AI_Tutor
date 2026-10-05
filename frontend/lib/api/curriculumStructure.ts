import type {
  CurriculumConcept,
  CurriculumCluster,
  CurriculumPublishResult,
  CurriculumTopicSource,
  CurriculumTree,
  CurriculumValidation,
  CurriculumZone,
} from "../types";

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

/** Visual payload accepted on concept save; `storage_key` comes from upload. */
export type StoryHookVisualInput = {
  id?: string;
  asset_key: string;
  storage_key: string;
  description?: string;
  teaching_purpose?: string;
  mime_type?: string;
};

export type StoryHookInput = {
  title: string;
  body: string;
  teacher_intent?: string;
  visuals?: StoryHookVisualInput[];
};

/** Result of uploading one Story Hook image, before the concept is saved. */
export type StoryHookVisualUpload = {
  id: string;
  asset_key: string;
  storage_key: string;
  mime_type: string;
  size_bytes: number;
};

/**
 * Slugify an author-supplied asset key to match backend ``normalize_asset_key``:
 * lowercase, ``a-z0-9_`` only, max 64 chars.
 */
export function normalizeAssetKey(
  raw: string | null | undefined,
  index = 0
): string {
  const fallback = `visual_${index + 1}`;
  let slug = String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  slug = slug.replace(/_{2,}/g, "_");
  return (slug || fallback).slice(0, 64);
}

/** Match backend ``dedupe_asset_key``: ``key``, then ``key-2``, ``key-3``, … */
export function dedupeAssetKey(candidate: string, taken: string[]): string {
  const used = new Set(taken);
  if (!used.has(candidate)) return candidate;
  let suffix = 2;
  while (used.has(`${candidate}-${suffix}`)) suffix += 1;
  return `${candidate}-${suffix}`;
}

/** Normalize + dedupe a visual list the same way concept save does on the server. */
export function normalizeStoryHookVisualAssetKeys(
  visuals: StoryHookVisualInput[]
): StoryHookVisualInput[] {
  const keys: string[] = [];
  return visuals.map((v, i) => {
    const asset_key = dedupeAssetKey(normalizeAssetKey(v.asset_key, i), keys);
    keys.push(asset_key);
    return {
      ...v,
      asset_key,
      description: v.description?.trim() ?? "",
      teaching_purpose: v.teaching_purpose?.trim() ?? "",
    };
  });
}

export async function uploadStoryHookVisual(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource,
  file: File
): Promise<StoryHookVisualUpload> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/story-hook/visuals` +
      `?topic_source=${encodeURIComponent(topicSource)}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as StoryHookVisualUpload;
}

/** Authenticated media URL for a committed Story Hook visual. */
export function storyHookVisualUrl(conceptId: string, assetKey: string): string {
  return (
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}` +
    `/story-hook/visuals/${encodeURIComponent(assetKey)}`
  );
}

/** Visual Teaching image draft accepted on concept save. */
export type VisualTeachingRegionInput = {
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
  /** VTSE visuals only. Visual Teaching leaves this unset. */
  bindings?: Array<{
    slot_kind: string;
    slot_key: string;
    slot_index: number;
    side: string;
  }>;
};

export type VisualTeachingAnchorInput = {
  anchor_id: string;
  label?: string;
  point: { x: number; y: number };
};

export type VisualTeachingConnectionInput = {
  connection_id: string;
  from_anchor: string;
  to_anchor: string;
  label?: string;
  teaching_purpose?: string;
  /** Internal default `flow` — not exposed in authoring UI. */
  kind?: "flow" | "compare" | "generic";
  color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
  label_box?: { x: number; y: number; w: number; h: number } | null;
};

export type VisualTeachingImageInput = {
  id?: string;
  asset_key: string;
  storage_key: string;
  mime_type?: string;
  title?: string;
  teaching_purpose?: string;
  natural_width?: number;
  natural_height?: number;
  content_hash?: string;
  annotations_status?: "confirmed" | "stale";
  regions?: VisualTeachingRegionInput[];
  anchors?: VisualTeachingAnchorInput[];
  connections?: VisualTeachingConnectionInput[];
};

export type VisualTeachingInput = {
  images: VisualTeachingImageInput[];
};

export type VisualTeachingImageUpload = {
  id: string;
  asset_key: string;
  storage_key: string;
  mime_type: string;
  size_bytes: number;
  natural_width: number;
  natural_height: number;
  content_hash: string;
  annotations_status: "confirmed" | "stale";
};

/** Normalize + dedupe Visual Teaching asset keys like concept save. */
export function normalizeVisualTeachingAssetKeys(
  images: VisualTeachingImageInput[]
): VisualTeachingImageInput[] {
  const keys: string[] = [];
  return images.map((img, i) => {
    const asset_key = dedupeAssetKey(normalizeAssetKey(img.asset_key, i), keys);
    keys.push(asset_key);
    return {
      ...img,
      asset_key,
      title: img.title?.trim() ?? "",
      teaching_purpose: img.teaching_purpose?.trim() ?? "",
      annotations_status:
        img.annotations_status === "stale" ? "stale" : "confirmed",
    };
  });
}

export async function uploadVisualTeachingImage(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource,
  file: File,
  opts?: { replaceAssetKey?: string }
): Promise<VisualTeachingImageUpload> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ topic_source: topicSource });
  if (opts?.replaceAssetKey) {
    qs.set("replace_asset_key", opts.replaceAssetKey);
  }
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/visual-teaching/images` +
      `?${qs.toString()}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as VisualTeachingImageUpload;
}

/** Authenticated media URL for a committed Visual Teaching image. */
export async function uploadVtseVisualImage(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource,
  file: File,
  opts?: { replaceAssetKey?: string }
): Promise<VisualTeachingImageUpload> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ topic_source: topicSource });
  if (opts?.replaceAssetKey) {
    qs.set("replace_asset_key", opts.replaceAssetKey);
  }
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/vtse-visuals/images` +
      `?${qs.toString()}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as VisualTeachingImageUpload;
}

export function vtseVisualImageUrl(conceptId: string, assetKey: string): string {
  return (
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}` +
    `/vtse-visuals/images/${encodeURIComponent(assetKey)}`
  );
}

export function visualTeachingImageUrl(
  conceptId: string,
  assetKey: string
): string {
  return (
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}` +
    `/visual-teaching/images/${encodeURIComponent(assetKey)}`
  );
}

/** Absolute URL for an API-relative media path returned by the tutor runtime. */
export function apiMediaUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    const detail = j?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((e: { msg?: string }) => e.msg ?? "").filter(Boolean).join("; ");
    }
    if (detail && typeof detail === "object") {
      const d = detail as {
        message?: string;
        code?: string;
        errors?: Array<{ message?: string; path?: string }>;
      };
      if (typeof d.message === "string") return d.message;
      if (Array.isArray(d.errors) && d.errors.length > 0) {
        return d.errors
          .map((e) => {
            const msg = e.message?.trim() ?? "";
            const path = e.path?.trim() ?? "";
            return path ? `${path}: ${msg}` : msg;
          })
          .filter(Boolean)
          .join("; ");
      }
    }
  } catch {
    /* ignore */
  }
  return res.statusText || "Request failed";
}

function topicParams(topicSource: CurriculumTopicSource): string {
  return `topic_source=${encodeURIComponent(topicSource)}`;
}

export async function getTopicCurriculumTree(
  token: string,
  topicId: string,
  topicSource: CurriculumTopicSource
): Promise<CurriculumTree> {
  const res = await fetch(
    `${API_BASE}/topics/${encodeURIComponent(topicId)}/curriculum?${topicParams(topicSource)}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumTree>;
}

export async function validateTopicCurriculum(
  token: string,
  topicId: string,
  topicSource: CurriculumTopicSource
): Promise<CurriculumValidation> {
  const res = await fetch(
    `${API_BASE}/topics/${encodeURIComponent(topicId)}/curriculum/validate?${topicParams(topicSource)}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumValidation>;
}

export async function publishTopicCurriculum(
  token: string,
  topicId: string,
  topicSource: CurriculumTopicSource
): Promise<CurriculumPublishResult> {
  const res = await fetch(
    `${API_BASE}/topics/${encodeURIComponent(topicId)}/curriculum/publish?${topicParams(topicSource)}`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumPublishResult>;
}

export async function unpublishTopicCurriculum(
  token: string,
  topicId: string,
  topicSource: CurriculumTopicSource
): Promise<CurriculumPublishResult> {
  const res = await fetch(
    `${API_BASE}/topics/${encodeURIComponent(topicId)}/curriculum/unpublish?${topicParams(topicSource)}`,
    { method: "POST", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumPublishResult>;
}

export async function createCurriculumZone(
  token: string,
  body: {
    topic_id: string;
    topic_source: CurriculumTopicSource;
    zone_number: number;
    title: string;
    description?: string;
    sort_order?: number;
  }
): Promise<CurriculumZone> {
  const res = await fetch(`${API_BASE}/curriculum/zones`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumZone>;
}

/** Promote a new topic to v2 structured curriculum (first zone seeds the tree). */
export async function ensureV2CurriculumStarted(
  token: string,
  topicId: string,
  topicSource: CurriculumTopicSource
): Promise<void> {
  try {
    const tree = await getTopicCurriculumTree(token, topicId, topicSource);
    if (tree.curriculum_schema_version === "v2" && tree.zones.length > 0) return;
    if (tree.zones.some((z) => z.zone_number === 1)) return;
    await createCurriculumZone(token, {
      topic_id: topicId,
      topic_source: topicSource,
      zone_number: 1,
      title: "Core Teaching",
    });
  } catch {
    /* Builder can recover if seed zone fails */
  }
}

export async function updateCurriculumZone(
  token: string,
  zoneId: string,
  body: {
    topic_source: CurriculumTopicSource;
    title?: string;
    description?: string;
    sort_order?: number;
  }
): Promise<CurriculumZone> {
  const res = await fetch(`${API_BASE}/curriculum/zones/${encodeURIComponent(zoneId)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumZone>;
}

export async function deleteCurriculumZone(
  token: string,
  zoneId: string,
  topicSource: CurriculumTopicSource
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/curriculum/zones/${encodeURIComponent(zoneId)}?${topicParams(topicSource)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function createCurriculumCluster(
  token: string,
  body: {
    topic_id: string;
    topic_source: CurriculumTopicSource;
    curriculum_zone_id: string;
    title: string;
    cluster_number?: number;
    sort_order?: number;
    estimated_learning_minutes?: number;
  }
): Promise<CurriculumCluster> {
  const res = await fetch(`${API_BASE}/curriculum/clusters`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumCluster>;
}

export async function updateCurriculumCluster(
  token: string,
  clusterId: string,
  body: {
    topic_source: CurriculumTopicSource;
    title?: string;
    description?: string;
    study_points?: string[];
    learning_outcomes?: string[];
    sort_order?: number;
    estimated_learning_minutes?: number | null;
  }
): Promise<CurriculumCluster> {
  const res = await fetch(
    `${API_BASE}/curriculum/clusters/${encodeURIComponent(clusterId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumCluster>;
}

export async function deleteCurriculumCluster(
  token: string,
  clusterId: string,
  topicSource: CurriculumTopicSource
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/curriculum/clusters/${encodeURIComponent(clusterId)}?${topicParams(topicSource)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function createCurriculumConcept(
  token: string,
  body: {
    topic_id: string;
    topic_source: CurriculumTopicSource;
    curriculum_cluster_id: string;
    display_name: string;
    slug?: string;
    sort_order?: number;
    difficulty_level?: string;
    estimated_learning_minutes?: number;
    study_points?: string[];
    learning_outcomes?: string[];
    story_hook?: StoryHookInput | null;
    visual_teaching?: VisualTeachingInput | null;
    teaching_sequence?: Array<"vtse" | "story_hook" | "visual_teaching" | "media">;
    vtse_template?: import("../types").ConceptVtseTemplate | null;
    legacy_concept_key?: string;
  }
): Promise<CurriculumConcept> {
  const res = await fetch(`${API_BASE}/curriculum/concepts`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumConcept>;
}

export async function getCurriculumConcept(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource
): Promise<CurriculumConcept> {
  const qs = new URLSearchParams({ topic_source: topicSource });
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}?${qs}`,
    {
      method: "GET",
      headers: authHeaders(token),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumConcept>;
}

export async function updateCurriculumConcept(
  token: string,
  conceptId: string,
  body: {
    topic_source: CurriculumTopicSource;
    display_name?: string;
    sort_order?: number;
    difficulty_level?: string;
    estimated_learning_minutes?: number | null;
    study_points?: string[];
    learning_outcomes?: string[];
    story_hook?: StoryHookInput | null;
    visual_teaching?: VisualTeachingInput | null;
    teaching_sequence?: Array<"vtse" | "story_hook" | "visual_teaching" | "media">;
    teaching_sequence_mode?: "manual" | "auto";
    vtse_template?: import("../types").ConceptVtseTemplate | null;
    vtse_visuals?: import("../types").VtseVisuals | null;
    canonical_runtime_key?: string;
  }
): Promise<CurriculumConcept> {
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}`,
    {
      method: "PUT",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumConcept>;
}

export async function previewTeachingOrder(
  token: string,
  conceptId: string,
  body: { topic_source: CurriculumTopicSource; regenerate?: boolean }
): Promise<CurriculumConcept> {
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/teaching-order/preview`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumConcept>;
}

export async function moveCurriculumConcept(
  token: string,
  conceptId: string,
  body: {
    topic_source: CurriculumTopicSource;
    target_cluster_id: string;
    target_index: number;
  }
): Promise<CurriculumConcept> {
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/move`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<CurriculumConcept>;
}

export async function deleteCurriculumConcept(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}?${topicParams(topicSource)}`,
    { method: "DELETE", headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getConceptUsage(
  token: string,
  conceptId: string,
  topicSource: CurriculumTopicSource
): Promise<import("../types").ConceptUsage> {
  const res = await fetch(
    `${API_BASE}/curriculum/concepts/${encodeURIComponent(conceptId)}/usage?${topicParams(topicSource)}`,
    { headers: authHeaders(token) }
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<import("../types").ConceptUsage>;
}
