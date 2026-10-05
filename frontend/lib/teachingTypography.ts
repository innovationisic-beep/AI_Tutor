/** Zone 0 whiteboard — matches Zone 1 VTSE explanation scale (16px / 21px Patrick Hand). */
export const WHITEBOARD_TEXT_CLASS = "whiteboard-teaching-text";

/** Chat body copy — same family and rhythm as the whiteboard. */
export const CHAT_TEXT_CLASS =
  "font-handwriting text-base leading-relaxed md:text-lg";

/** Chat labels, hints, and secondary lines. */
export const CHAT_META_TEXT_CLASS =
  "font-handwriting text-sm leading-relaxed";

/** Chat inputs and text areas. */
export const CHAT_INPUT_TEXT_CLASS =
  "font-handwriting text-base leading-relaxed md:text-lg";

/** VTSE timeline SVG labels (hierarchy, flow, cycle, comparison). */
export const TIMELINE_SVG_TEXT_CLASS = "font-handwriting";

/** Injected into MinimalDeterministicRenderer — SVG <text> does not inherit HTML font classes. */
export const TIMELINE_SVG_TEXT_CSS = `
  .v3-minimal-deterministic-renderer text,
  .v3-minimal-deterministic-renderer tspan {
    font-family: var(--font-handwriting), cursive;
  }
`;

/** VTSE diagram text scale (hierarchy, flow, cycle, comparison). */
export const TIMELINE_ANNOTATION_FONT_SIZE = 16;
export const TIMELINE_ANNOTATION_LINE_HEIGHT = 21;
export const TIMELINE_ANNOTATION_PAD = 16;
export const TIMELINE_ANNOTATION_FONT_COMPRESSED = 13;
export const TIMELINE_ANNOTATION_FONT_TRANSIENT = 12;
export const TIMELINE_ANNOTATION_LINE_HEIGHT_COMPRESSED = 18;
export const TIMELINE_ANNOTATION_LINE_HEIGHT_TRANSIENT = 16;

export const TIMELINE_NODE_FONT_PROCESS = 17;
export const TIMELINE_NODE_FONT_ROOT = 19;
export const TIMELINE_NODE_FONT_DEFAULT = 18;
export const TIMELINE_STEP_LABEL_FONT_SIZE = 14;

export const TIMELINE_LABEL_FONT_SIZE = 16;

export const TIMELINE_COMPARISON_FONT_SIZE = 16;
export const TIMELINE_COMPARISON_LINE_HEIGHT = 21;
export const TIMELINE_COMPARISON_DIMENSION_FONT_SIZE = 12;
export const TIMELINE_COMPARISON_DIMENSION_RESERVE = 18;

/** Average px per character for handwriting wrap width (Patrick Hand ~16px). */
export const TIMELINE_CHAR_PX = 6.4;

/** Fallback wrap width when card pixel width is unknown. */
export const TIMELINE_WRAP_CHARS_FALLBACK = 30;

/** Max characters per line from explanation-card pixel width (SVG has no auto-wrap). */
export function timelineCharsPerLine(
  boxWidth: number,
  pad: number = TIMELINE_ANNOTATION_PAD,
  safetyPx = 4,
): number {
  const inner = Math.max(80, boxWidth - pad * 2 - safetyPx);
  return Math.max(18, Math.floor(inner / TIMELINE_CHAR_PX));
}

/** Approximate px width of one character at a given SVG font size. */
export function timelineCharWidthPx(fontSize: number): number {
  return fontSize * (TIMELINE_CHAR_PX / TIMELINE_ANNOTATION_FONT_SIZE);
}

export const TIMELINE_EXPLANATION_LINE_HEIGHT = TIMELINE_ANNOTATION_LINE_HEIGHT;
