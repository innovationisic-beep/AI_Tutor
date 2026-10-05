/** Presentation-only: turn paragraph explanations into concise teaching bullets. */

export const TEACHING_BULLET_MARKER = "•";
export const TEACHING_BULLET_MIN = 1;
export const TEACHING_BULLET_MAX = 5;

const SENTENCE_SPLIT = /(?<=[.!?])\s+(?=[A-Z0-9"“])/;

function stripTrailingPeriod(sentence: string): string {
  return sentence.replace(/[.!?]+\s*$/u, "").trim();
}

function normalizeBulletLine(line: string): string {
  const trimmed = line.trim();
  if (!trimmed) return "";
  const stripped = trimmed.replace(/^[\u2022•\-*]\s+/u, "").trim();
  return stripped ? `${TEACHING_BULLET_MARKER} ${stripTrailingPeriod(stripped)}` : "";
}

function splitIntoSentences(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (SENTENCE_SPLIT.test(trimmed)) {
    return trimmed
      .split(SENTENCE_SPLIT)
      .map((s) => s.trim())
      .filter((s) => s.length >= 3);
  }

  if (trimmed.includes(";")) {
    return trimmed
      .split(/\s*;\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 3);
  }

  return [trimmed];
}

function alreadyBulleted(text: string): boolean {
  const lines = text
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length < 2) return /^[\u2022•\-*]\s/.test(text.trim());
  return lines.every((l) => /^[\u2022•\-*]\s/.test(l));
}

function bulletsForWrap(text: string, maxBullets: number = TEACHING_BULLET_MAX): string[] {
  const trimmed = (text ?? "").trim();
  if (!trimmed) return [];
  if (trimmed.includes("\n") && /^[\u2022•]/u.test(trimmed)) {
    return trimmed
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, maxBullets);
  }
  return formatTeachingExplanationBullets(trimmed, maxBullets);
}

/** Split explanation prose into 1–5 concise bullet lines (presentation only). */
export function formatTeachingExplanationBullets(
  text: string,
  maxBullets: number = TEACHING_BULLET_MAX,
): string[] {
  const trimmed = (text ?? "").trim();
  if (!trimmed) return [];

  if (alreadyBulleted(trimmed)) {
    const lines = trimmed
      .split(/\n+/)
      .map(normalizeBulletLine)
      .filter(Boolean);
    return lines.slice(0, maxBullets);
  }

  const sentences = splitIntoSentences(trimmed);
  const capped = Math.max(TEACHING_BULLET_MIN, Math.min(maxBullets, TEACHING_BULLET_MAX));
  const bullets = sentences
    .slice(0, capped)
    .map((s) => `${TEACHING_BULLET_MARKER} ${stripTrailingPeriod(s)}`)
    .filter((b) => b.length > 2);

  if (bullets.length > 0) return bullets;
  return [`${TEACHING_BULLET_MARKER} ${stripTrailingPeriod(trimmed)}`];
}

/** Newline-joined bullets for HTML / speech-sync display. */
export function teachingExplanationPlain(text: string): string {
  return formatTeachingExplanationBullets(text).join("\n");
}

function wrapSingleBulletLine(line: string, maxChars: number): string[] {
  if (line.length <= maxChars) return [line];
  const words = line.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length <= maxChars) {
      current = next;
      continue;
    }
    if (current) lines.push(current);
    current = word.length > maxChars ? word.slice(0, maxChars) : word;
  }
  if (current) lines.push(current);
  return lines.length ? lines : [line.slice(0, maxChars)];
}

/** Wrap bullets for fixed-width explanation cards (flow, hierarchy, cycle). */
export function wrapTeachingExplanationLines(text: string, maxCharsPerLine: number): string[] {
  const bullets = bulletsForWrap(text);
  const maxChars = Math.max(12, maxCharsPerLine);
  const lines: string[] = [];
  for (const bullet of bullets) {
    lines.push(...wrapSingleBulletLine(bullet, maxChars));
  }
  return lines.length ? lines : [" "];
}

/** Wrap bullets for comparison row cells with a line budget. */
export function wrapTeachingExplanationForRow(
  text: string,
  maxCharsPerLine: number,
  maxLines: number,
): string[] {
  const bullets = bulletsForWrap(text);
  const maxChars = Math.max(12, maxCharsPerLine);
  const cap = Math.max(1, maxLines);
  const lines: string[] = [];
  for (const bullet of bullets) {
    for (const part of wrapSingleBulletLine(bullet, maxChars)) {
      lines.push(part);
      if (lines.length >= cap) return lines;
    }
  }
  return lines.length ? lines : [""];
}
