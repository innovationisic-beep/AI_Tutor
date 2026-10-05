/**
 * Supported-capabilities contract for Visual Teaching.
 * Must match backend `SUPPORTED_VISUAL_CAPABILITIES`.
 */

export const ALL_VISUAL_CAPABILITY_KEYS = [
  "highlights",
  "pointer",
  "labels_visible",
  "dim_others",
  "zoom",
  "arrows",
  "enter_effects",
  "sentence_visual_patches",
] as const;

export type VisualCapability = (typeof ALL_VISUAL_CAPABILITY_KEYS)[number];

export const SUPPORTED_VISUAL_CAPABILITIES: ReadonlySet<string> = new Set([
  "highlights",
  "pointer",
  "labels_visible",
  "dim_others",
  "zoom",
  "arrows",
  "enter_effects",
  "sentence_visual_patches",
]);

export function isCapabilitySupported(name: string): boolean {
  return SUPPORTED_VISUAL_CAPABILITIES.has(String(name || "").trim());
}

export function unsupportedIn(used: Iterable<string>): string[] {
  return [...used].filter((c) => !isCapabilitySupported(String(c))).sort();
}
