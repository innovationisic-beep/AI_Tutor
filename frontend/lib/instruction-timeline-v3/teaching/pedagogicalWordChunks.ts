/**
 * Word-level chunks — TTS and on-board text use the same string, revealed word-by-word.
 */

export function wordChunks(text: string): string[] {
  return text.replace(/\s+/g, " ").trim().split(/\s+/).filter(Boolean);
}

export function joinWordChunks(words: readonly string[], throughIndex: number): string {
  if (throughIndex < 0 || words.length === 0) return "";
  return words.slice(0, throughIndex + 1).join(" ");
}

export function visibleTextForWordIndex(fullText: string, wordIndex: number): string {
  const words = wordChunks(fullText);
  if (words.length === 0) return "";
  const idx = Math.min(wordIndex, words.length - 1);
  return joinWordChunks(words, idx);
}
