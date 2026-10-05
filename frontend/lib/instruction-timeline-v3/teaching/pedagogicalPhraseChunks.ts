/**
 * Semantic phrase chunks for speech-synchronized pedagogical reveal.
 * Not character-by-character — clause / phrase boundaries for teacher-like pacing.
 */

const CLAUSE_CONJUNCTION =
  /\s+(?=(?:because|while|whereas|although|however|therefore|thus|hence|so that|in contrast|in addition|for example|and then|but also|yet|though)\s)/i;

const MAX_CHUNK_CHARS = 88;
const MIN_CHUNK_CHARS = 6;

function splitLongPhrase(text: string): string[] {
  const trimmed = text.trim();
  if (trimmed.length <= MAX_CHUNK_CHARS) return trimmed ? [trimmed] : [];

  const commaParts = trimmed.split(/,\s+/);
  if (commaParts.length > 1) {
    const out: string[] = [];
    let acc = "";
    for (const part of commaParts) {
      const candidate = acc ? `${acc}, ${part}` : part;
      if (candidate.length <= MAX_CHUNK_CHARS) {
        acc = candidate;
      } else {
        if (acc) out.push(acc);
        acc = part;
      }
    }
    if (acc) out.push(acc);
    return out;
  }

  const words = trimmed.split(/\s+/);
  const out: string[] = [];
  let acc = "";
  for (const word of words) {
    const candidate = acc ? `${acc} ${word}` : word;
    if (candidate.length <= MAX_CHUNK_CHARS) {
      acc = candidate;
    } else {
      if (acc) out.push(acc);
      acc = word;
    }
  }
  if (acc) out.push(acc);
  return out;
}

function mergeTinyChunks(chunks: string[]): string[] {
  if (chunks.length <= 1) return chunks;
  const out: string[] = [];
  for (const chunk of chunks) {
    if (out.length > 0 && chunk.length < MIN_CHUNK_CHARS) {
      out[out.length - 1] = `${out[out.length - 1]} ${chunk}`;
    } else {
      out.push(chunk);
    }
  }
  return out;
}

function splitSentenceIntoPhrases(sentence: string): string[] {
  const trimmed = sentence.trim();
  if (!trimmed) return [];

  const clauseParts = trimmed.split(CLAUSE_CONJUNCTION).map((s) => s.trim()).filter(Boolean);
  const phrases: string[] = [];
  for (const part of clauseParts) {
    phrases.push(...splitLongPhrase(part));
  }
  return mergeTinyChunks(phrases);
}

/**
 * Deterministic spoken-sentence split — must match backend `split_spoken_sentences`.
 */
export function splitSpokenSentences(text: string): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  return normalized
    .split(/(?<=[.?!])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export type BoardWrite = {
  sentenceIndex: number;
  text: string;
};

/**
 * Map spoken word progress → completed sentence index (0-based).
 * A sentence is completed once its last word has been revealed.
 */
export function completedSentenceIndexForSpeechProgress(
  spokenText: string,
  narrationChunkIndex: number,
  narrationChunkCount: number,
): number {
  const sentences = splitSpokenSentences(spokenText);
  if (sentences.length === 0 || narrationChunkCount <= 0) return -1;
  if (narrationChunkIndex >= narrationChunkCount - 1) {
    return sentences.length - 1;
  }

  const wordsPerSentence = sentences.map((s) =>
    s.trim() ? s.trim().split(/\s+/).length : 0
  );
  let cumulative = 0;
  let completed = -1;
  for (let i = 0; i < wordsPerSentence.length; i++) {
    cumulative += wordsPerSentence[i];
    // chunkIndex is 0-based word index; sentence completes when index reaches last word.
    if (narrationChunkIndex + 1 >= cumulative) {
      completed = i;
    } else {
      break;
    }
  }
  return completed;
}

/**
 * Sentence-anchored board ink: whole write chunks when their sentence is reached.
 */
export function boardInkForSpeechProgress(
  spokenText: string,
  writes: readonly BoardWrite[],
  narrationChunkIndex: number,
  narrationChunkCount: number,
): string {
  if (!writes.length) return "";
  const completed = completedSentenceIndexForSpeechProgress(
    spokenText,
    narrationChunkIndex,
    narrationChunkCount,
  );
  if (completed < 0) return "";
  const visible = writes
    .filter((w) => w.sentenceIndex <= completed && String(w.text || "").trim())
    .sort((a, b) => a.sentenceIndex - b.sentenceIndex)
    .map((w) => w.text.trim());
  return visible.join("\n");
}

/**
 * Split prose into pedagogical phrase chunks (clauses, commas, sentence boundaries).
 */
export function pedagogicalPhraseChunks(text: string): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return [];

  const sentences = splitSpokenSentences(normalized);
  const chunks: string[] = [];
  for (const sentence of sentences) {
    chunks.push(...splitSentenceIntoPhrases(sentence));
  }
  return mergeTinyChunks(chunks.filter(Boolean));
}

/** Join revealed chunks with natural spacing (preserves clause flow). */
export function joinPhraseChunks(chunks: readonly string[], throughIndex: number): string {
  if (throughIndex < 0 || chunks.length === 0) return "";
  const slice = chunks.slice(0, throughIndex + 1);
  return slice.join(" ").trim();
}

/**
 * Map narration progress to display text when spoken words differ from on-board copy.
 */
export function visibleTextForNarrationProgress(
  displayFullText: string,
  narrationChunkIndex: number,
  narrationChunkCount: number,
): string {
  const full = displayFullText.trim();
  if (!full || narrationChunkCount <= 0) return "";
  if (narrationChunkIndex >= narrationChunkCount - 1) return full;

  const displayChunks = pedagogicalPhraseChunks(full);
  if (displayChunks.length <= 1) {
    const progress = (narrationChunkIndex + 1) / narrationChunkCount;
    if (progress >= 1) return full;
    const words = full.split(/\s+/);
    const visibleWords = Math.max(1, Math.ceil(progress * words.length));
    return words.slice(0, visibleWords).join(" ");
  }

  const progress = (narrationChunkIndex + 1) / narrationChunkCount;
  const visibleCount = Math.max(1, Math.ceil(progress * displayChunks.length));
  return joinPhraseChunks(displayChunks, visibleCount - 1);
}
