/** Color helpers for Visual Teaching region styling. */

export const DEFAULT_HIGHLIGHT_COLOR = "#f59e0b";
export const DEFAULT_LABEL_BG_COLOR = "#0f172a";
export const DEFAULT_LABEL_TEXT_COLOR = "#f8fafc";
export const DEFAULT_ARROW_COLOR = "#0ea5e9";

const HEX6 = /^#[0-9a-fA-F]{6}$/;
const HEX3 = /^#[0-9a-fA-F]{3}$/;

export function normalizeHexColor(raw: unknown, fallback: string): string {
  if (typeof raw !== "string") return fallback;
  const s = raw.trim();
  if (HEX6.test(s)) return s.toLowerCase();
  if (HEX3.test(s)) {
    const r = s[1]!;
    const g = s[2]!;
    const b = s[3]!;
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return fallback;
}

export function hexToRgba(hex: string, alpha: number): string {
  const h = normalizeHexColor(hex, DEFAULT_HIGHLIGHT_COLOR);
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  const a = Math.min(1, Math.max(0, alpha));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/**
 * Fit label font inside a pixel/viewBox-sized chrome box so text stays covered.
 */
export function fitLabelFontSize(
  boxW: number,
  boxH: number,
  textLen: number
): { fontSize: number; padX: number; padY: number } {
  const padX = Math.max(4, Math.min(boxW * 0.08, boxH * 0.22));
  const padY = Math.max(3, Math.min(boxH * 0.16, boxW * 0.1));
  const innerW = Math.max(4, boxW - padX * 2);
  const innerH = Math.max(4, boxH - padY * 2);
  const byH = innerH * 0.82;
  // ~0.55em average glyph width for system-ui bold.
  const byW = innerW / Math.max(1, textLen * 0.55);
  const fontSize = Math.max(14, Math.min(byH, byW));
  return { fontSize, padX, padY };
}
