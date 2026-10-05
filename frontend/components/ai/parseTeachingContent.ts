/**
 * Parse tutor-style responses into intro, bullets, example, and summary.
 * - Example: ends before any summary starter (Quick summary:, So in short, etc.)
 * - Supports "Example" as a heading line without ":" and inline "example:"
 */

function findExampleColonMarker(
  t: string
): { index: number; length: number } | null {
  const re = /example\s*:/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(t)) !== null) {
    const start = m.index;
    const before = t.slice(Math.max(0, start - 12), start).toLowerCase();
    if (/\bfor\s+$/.test(before)) continue;
    return { index: start, length: m[0].length };
  }
  return null;
}

/** "Example" or "Example:" as the only text on a line (optional indent). */
function findExampleHeadingLine(
  t: string
): { index: number; length: number } | null {
  const re = /^(\s*)(example\s*:?)\s*$/gim;
  let m: RegExpExecArray | null;
  while ((m = re.exec(t)) !== null) {
    const wordStart = m.index + m[1].length;
    let end = m.index + m[0].length;
    while (end < t.length && (t[end] === "\n" || t[end] === "\r")) {
      end += 1;
    }
    return { index: wordStart, length: end - wordStart };
  }
  return null;
}

function findExampleStart(t: string): { index: number; length: number } | null {
  const colon = findExampleColonMarker(t);
  const heading = findExampleHeadingLine(t);
  if (!colon && !heading) return null;
  if (!heading) return colon;
  if (!colon) return heading;
  if (colon.index < heading.index) return colon;
  if (heading.index < colon.index) return heading;
  return heading;
}

/**
 * First summary marker at or after minIndex (so "So, in short" in intro is ignored
 * when we only search after the example block start).
 */
function findSummaryStartFrom(
  t: string,
  minIndex: number
): { index: number; length: number } | null {
  const slice = t.slice(minIndex);
  const patterns: RegExp[] = [
    /quick\s*summary\s*:/i,
    /\bso,\s*in\s+short,?\s+/i,
    /\bto\s+sum\s+up,?\s+/i,
    /\bin\s+summary,?\s+/i,
  ];
  let best: { index: number; length: number } | null = null;
  for (const re of patterns) {
    const m = re.exec(slice);
    if (!m) continue;
    const absIdx = minIndex + m.index;
    if (!best || absIdx < best.index) {
      best = { index: absIdx, length: m[0].length };
    }
  }
  return best;
}

export function parseTeachingContent(text: string) {
  const t = text.replace(/\*\*/g, "").replace(/\*/g, "").trim();

  if (!t) {
    return {
      intro: "",
      bullets: [] as string[],
      example: "",
      summary: "",
    };
  }

  const ex = findExampleStart(t);
  const exIdx = ex?.index ?? -1;
  const exEnd = ex ? ex.index + ex.length : -1;

  let introRaw = "";
  let example = "";
  let summary = "";

  if (exIdx >= 0) {
    introRaw = t.slice(0, exIdx).trim();
    const afterEx = t.slice(exEnd);
    const sum = findSummaryStartFrom(t, exEnd);
    if (sum) {
      const rel = sum.index - exEnd;
      example = afterEx.slice(0, rel).trim();
      summary = t.slice(sum.index + sum.length).trim();
    } else {
      example = afterEx.trim();
    }
  } else {
    const sum = findSummaryStartFrom(t, 0);
    if (sum) {
      introRaw = t.slice(0, sum.index).trim();
      summary = t.slice(sum.index + sum.length).trim();
    } else {
      introRaw = t;
    }
  }

  const bullets: string[] = [];
  let intro = "";
  const lines = introRaw.split(/\n/).map((l) => l.trim()).filter(Boolean);

  for (const line of lines) {
    if (/^-\s*/.test(line)) {
      bullets.push(line.replace(/^-\s*/, "").trim());
    } else {
      intro += (intro ? " " : "") + line;
    }
  }

  if (
    bullets.length === 0 &&
    lines.length === 1 &&
    lines[0].includes(" - ")
  ) {
    const parts = lines[0]
      .split(/\s+-\s+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length >= 2) {
      intro = parts[0] ?? "";
      bullets.push(...parts.slice(1));
    }
  }

  return {
    intro: intro.trim(),
    bullets,
    example: example.trim(),
    summary: summary.trim(),
  };
}
