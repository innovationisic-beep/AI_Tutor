/** Presentation-only: pick 2–4 teaching keywords for subtle underline emphasis. */

export const TEACHING_KEYWORD_MIN = 2;
export const TEACHING_KEYWORD_MAX = 4;

const STOPWORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "been", "being", "both", "but", "by",
  "can", "could", "did", "do", "does", "each", "for", "from", "had", "has", "have",
  "he", "her", "here", "him", "his", "how", "if", "in", "into", "is", "it", "its",
  "just", "like", "make", "many", "may", "more", "most", "much", "must", "not", "of",
  "on", "one", "only", "or", "other", "our", "out", "over", "she", "should", "so",
  "some", "such", "than", "that", "the", "their", "them", "then", "there", "these",
  "they", "this", "those", "through", "to", "too", "under", "use", "used", "using",
  "very", "was", "we", "were", "what", "when", "where", "which", "while", "who",
  "why", "will", "with", "would", "you", "your",
]);

const SCIENCE_LEXICON = new Set([
  "absorb", "absorbed", "adapt", "cell", "cells", "cycle", "divide", "energy",
  "grow", "growth", "metabolism", "multiply", "nutrient", "nutrients", "organ",
  "organism", "oxygen", "photosynthesis", "produce", "release", "reproduce",
  "respiration", "transport", "water",
]);

export type KeywordSegment = {
  text: string;
  highlight: boolean;
};

function tokenizeWords(text: string): string[] {
  const stripped = text.replace(/^[\u2022•\-*]\s+/u, "").trim();
  const matches = stripped.match(/[A-Za-z][A-Za-z'-]*/g);
  return matches ?? [];
}

function normalizeToken(token: string): string {
  return token.toLowerCase().replace(/['']s$/u, "");
}

function stripPunctuation(token: string): string {
  return token.replace(/^[\u2022•\-*]+/u, "").replace(/[.,!?;:]+$/u, "");
}

/** Score and pick 2–4 keywords from node title + bullet lines (no LLM). */
export function extractTeachingKeywords(
  contextTitle: string | undefined,
  bulletLines: readonly string[],
  maxKeywords: number = TEACHING_KEYWORD_MAX,
  minKeywords: number = TEACHING_KEYWORD_MIN,
): ReadonlySet<string> {
  const scores = new Map<string, number>();
  const titleTokens = tokenizeWords(contextTitle ?? "");
  const titleNorm = new Set(titleTokens.map(normalizeToken));

  for (const token of titleTokens) {
    const norm = normalizeToken(token);
    if (norm.length >= 3 && !STOPWORDS.has(norm)) {
      scores.set(norm, (scores.get(norm) ?? 0) + 4);
    }
  }

  const prose = bulletLines.join(" ");
  for (const token of tokenizeWords(prose)) {
    const norm = normalizeToken(token);
    if (norm.length < 4 || STOPWORDS.has(norm)) continue;
    let score = 1;
    if (titleNorm.has(norm)) score += 5;
    if (SCIENCE_LEXICON.has(norm)) score += 3;
    if (/ing$|ed$|tion$|sion$|ysis$/u.test(norm)) score += 1;
    if (norm.length >= 7) score += 1;
    scores.set(norm, (scores.get(norm) ?? 0) + score);
  }

  const cap = Math.max(minKeywords, Math.min(maxKeywords, TEACHING_KEYWORD_MAX));
  const ranked = [...scores.entries()]
    .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)
    .map(([word]) => word)
    .slice(0, cap);

  return new Set(ranked);
}

/** Split a rendered line into segments for highlight styling. */
export function lineKeywordSegments(
  line: string,
  keywords: ReadonlySet<string>,
): KeywordSegment[] {
  if (!keywords.size || !line) return [{ text: line, highlight: false }];
  const parts = line.split(/(\s+)/u);
  return parts.map((part) => {
    if (/^\s+$/u.test(part)) return { text: part, highlight: false };
    const bare = stripPunctuation(part);
    const norm = normalizeToken(bare);
    return { text: part, highlight: norm.length >= 3 && keywords.has(norm) };
  });
}

export function shouldHighlightLine(
  lineIndex: number,
  visibleLineCount: number,
  speechPhase: "pending" | "speaking" | "stable" | null,
): boolean {
  if (speechPhase === "stable" || speechPhase === null) return true;
  if (speechPhase === "pending") return false;
  return lineIndex < visibleLineCount - 1;
}
