"use client";

import { AuthImage } from "@/components/media/AuthImage";
import { WordSyncedStreaming } from "@/components/ai/WordSyncedStreaming";
import { apiMediaUrl } from "@/lib/api/curriculumStructure";
import { WHITEBOARD_TEXT_CLASS } from "@/lib/teachingTypography";
import { cn } from "@/lib/utils";

export type StoryHookWritingMode = "legacy" | "notes";

export type ConceptStoryHookCardData = {
  heading: string;
  title: string;
  /** Visible writing on the card (note in notes mode, or spoken text in legacy). */
  body: string;
  imagePath?: string;
  imageAlt?: string;
  /** Optional concise note from planner (may be empty). */
  note?: string;
  writingMode?: StoryHookWritingMode;
  /** Full spoken narration when it differs from body. */
  spokenText?: string;
  /** Sentence-anchored board writes (validated indices). */
  boardWrites?: Array<{ sentenceIndex: number; text: string }>;
};

export type ConceptStoryHookStepView = ConceptStoryHookCardData & {
  id: string;
  /**
   * Text fed to WordSyncedStreaming as TTS source. Defaults to spoken/body.
   * Keep stable across rerenders so speech does not restart.
   */
  streamText?: string;
  /**
   * Visible writing for WSS. undefined = reveal streamText (legacy).
   * "" = speak-only. non-empty = reveal this note in sync.
   */
  displayText?: string;
  /** Sentence-anchored writes; preferred over displayText when non-empty. */
  boardWrites?: Array<{ sentenceIndex: number; text: string }>;
  /** Resume/restore: full reveal, no TTS. Do not flip this after live playback starts. */
  streamStaticMode?: boolean;
  onStreamComplete?: () => void;
};

type ConceptStoryHookCardProps = {
  /** Single-step legacy prop — prefer `steps` for multi-step runs. */
  card?: ConceptStoryHookCardData;
  /** Ordered steps from one Story Hook execution (one shared header). */
  steps?: ConceptStoryHookStepView[];
};

export function parseConceptStoryHookCard(
  visual: unknown
): ConceptStoryHookCardData | null {
  if (!visual || typeof visual !== "object") return null;
  const v = visual as Record<string, unknown>;
  if (v.type !== "concept_story_hook") return null;
  const card = v.card;
  if (!card || typeof card !== "object") return null;
  const c = card as Record<string, unknown>;
  const title = typeof c.title === "string" ? c.title.trim() : "";
  const body =
    typeof c.body === "string"
      ? c.body.trim()
      : typeof c.description === "string"
        ? c.description.trim()
        : "";
  const heading =
    typeof c.heading === "string" && c.heading.trim()
      ? c.heading.trim()
      : "STORY HOOK";
  const imagePath = typeof c.image_path === "string" ? c.image_path.trim() : "";
  const imageAlt = typeof c.image_alt === "string" ? c.image_alt.trim() : "";
  const note = typeof c.note === "string" ? c.note.trim() : "";
  const writingRaw =
    typeof c.writing_mode === "string" ? c.writing_mode.trim().toLowerCase() : "";
  const writingMode: StoryHookWritingMode | undefined =
    writingRaw === "notes"
      ? "notes"
      : writingRaw === "legacy"
        ? "legacy"
        : undefined;
  const spokenText =
    typeof c.spoken_text === "string" ? c.spoken_text.trim() : "";
  const boardWrites: Array<{ sentenceIndex: number; text: string }> = [];
  if (Array.isArray(c.writes)) {
    for (const item of c.writes) {
      if (!item || typeof item !== "object") continue;
      const rec = item as Record<string, unknown>;
      const idx = Number(rec.sentence_index);
      const wtext = typeof rec.text === "string" ? rec.text.trim() : "";
      if (!Number.isFinite(idx) || idx < 0 || !wtext) continue;
      boardWrites.push({ sentenceIndex: Math.floor(idx), text: wtext });
    }
  }
  if (!title && !body && !imagePath && !spokenText) return null;
  return {
    heading,
    title: title || heading,
    body,
    imagePath: imagePath || undefined,
    imageAlt: imageAlt || undefined,
    note: note || undefined,
    writingMode,
    spokenText: spokenText || undefined,
    boardWrites: boardWrites.length ? boardWrites : undefined,
  };
}

/** True when the step has durable board ink (writes or non-empty display/body note). */
function stepHasBoardInk(step: ConceptStoryHookStepView): boolean {
  if (step.boardWrites && step.boardWrites.length > 0) return true;
  if (step.displayText !== undefined) {
    return Boolean(String(step.displayText).trim());
  }
  // Legacy: reveal spoken text as ink.
  return Boolean(
    (step.streamText && step.streamText.trim() && step.streamText !== "\u00a0") ||
      step.spokenText?.trim() ||
      step.body?.trim()
  );
}

/** Speak-only notes step: dual display with empty ink, no image. */
function stepIsSpeakOnlyNoInk(step: ConceptStoryHookStepView): boolean {
  return (
    (!step.boardWrites || step.boardWrites.length === 0) &&
    step.displayText !== undefined &&
    !String(step.displayText).trim() &&
    !step.imagePath
  );
}

/** Visible card content besides pure TTS (image, question/ink, or legacy speech reveal). */
function stepHasVisibleBoardContent(step: ConceptStoryHookStepView): boolean {
  if (step.imagePath) return true;
  if (stepHasBoardInk(step)) return true;
  return false;
}

function StepBody({
  step,
  isFirst,
  bodyClassName,
}: {
  step: ConceptStoryHookStepView;
  isFirst: boolean;
  bodyClassName: string;
}) {
  const hasImage = Boolean(step.imagePath);
  const rawSpeak =
    (step.streamText != null && step.streamText.trim()
      ? step.streamText
      : step.spokenText || step.body) || "";
  const textForStream = rawSpeak.trim() ? rawSpeak : "\u00a0";
  const showStreamer = Boolean(
    rawSpeak.trim() ||
      step.onStreamComplete ||
      (!hasImage && step.streamText != null)
  );

  if (!hasImage && !showStreamer) return null;

  const speakOnly =
    (!step.boardWrites || step.boardWrites.length === 0) &&
    step.displayText !== undefined &&
    !String(step.displayText).trim();

  // Speak-only narration: keep WSS mounted for TTS/completion without card ink.
  if (speakOnly && !hasImage) {
    return (
      <div className="sr-only" aria-hidden>
        <WordSyncedStreaming
          text={textForStream}
          displayText=""
          staticMode={Boolean(step.streamStaticMode)}
          onComplete={step.onStreamComplete}
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        !isFirst && "mt-6 border-t border-amber-200/70 pt-6 dark:border-amber-900/50"
      )}
    >
      {hasImage ? (
        <AuthImage
          src={apiMediaUrl(step.imagePath!)}
          alt={step.imageAlt ?? step.title}
          className="max-h-80 w-full rounded-xl object-contain"
        />
      ) : null}
      {showStreamer ? (
        <WordSyncedStreaming
          text={textForStream}
          displayText={step.displayText}
          boardWrites={
            step.boardWrites && step.boardWrites.length
              ? step.boardWrites
              : undefined
          }
          className={cn(
            bodyClassName,
            hasImage ? "mt-4" : "",
            "text-slate-700 dark:text-slate-200",
            speakOnly ? "sr-only" : ""
          )}
          staticMode={Boolean(step.streamStaticMode)}
          onComplete={step.onStreamComplete}
        />
      ) : null}
    </div>
  );
}

/**
 * One Story Hook stage = one card. Pass `steps` to append narration / visuals /
 * questions / follow-ups in order under a single STORY HOOK header.
 * Narration bodies use WordSyncedStreaming (same as normal tutor responses).
 *
 * When every step is speak-only (no ink, no image), suppress card chrome and
 * keep only hidden TTS/completion drivers.
 */
export function ConceptStoryHookCard({ card, steps }: ConceptStoryHookCardProps) {
  const resolvedSteps: ConceptStoryHookStepView[] =
    steps && steps.length > 0
      ? steps
      : card
        ? [{ id: "single", ...card }]
        : [];
  if (resolvedSteps.length === 0) return null;

  const heading =
    resolvedSteps.find((s) => s.heading?.trim())?.heading?.trim() || "STORY HOOK";
  const title =
    resolvedSteps.find((s) => s.title?.trim())?.title?.trim() || heading;

  const hasAnyVisibleContent = resolvedSteps.some(stepHasVisibleBoardContent);

  // Zero visible board content: TTS/completion only — no empty card shell.
  if (!hasAnyVisibleContent) {
    return (
      <div className="sr-only" aria-hidden>
        {resolvedSteps.map((step) => {
          const rawSpeak =
            (step.streamText != null && step.streamText.trim()
              ? step.streamText
              : step.spokenText || step.body) || "";
          const textForStream = rawSpeak.trim() ? rawSpeak : "\u00a0";
          if (!textForStream.trim() && !step.onStreamComplete) return null;
          return (
            <WordSyncedStreaming
              key={step.id}
              text={textForStream}
              displayText=""
              staticMode={Boolean(step.streamStaticMode)}
              onComplete={step.onStreamComplete}
            />
          );
        })}
      </div>
    );
  }

  let visibleIndex = 0;
  return (
    <article
      className={cn(
        "mx-auto max-w-2xl rounded-2xl border-2 p-6 shadow-md md:p-8",
        "border-amber-300 bg-gradient-to-br from-amber-50 via-white to-orange-50",
        "dark:border-amber-800 dark:from-amber-950/40 dark:via-slate-900 dark:to-orange-950/20"
      )}
      aria-label={`${heading}: ${title}`}
    >
      <header className="border-b border-slate-200/80 pb-4 text-center dark:border-slate-700">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          {heading}
        </p>
        <h3
          className={cn(
            WHITEBOARD_TEXT_CLASS,
            "mt-2 text-2xl font-bold text-slate-900 md:text-3xl dark:text-slate-50"
          )}
        >
          {title}
        </h3>
      </header>
      <div className="mt-6 space-y-0">
        {resolvedSteps.map((step) => {
          const hasContent = Boolean(
            step.body ||
              step.imagePath ||
              step.streamText ||
              step.spokenText ||
              step.onStreamComplete ||
              step.displayText !== undefined ||
              (step.boardWrites && step.boardWrites.length)
          );
          if (!hasContent) return null;
          const speakOnlyNoInk = stepIsSpeakOnlyNoInk(step);
          const isFirst = visibleIndex === 0;
          if (!speakOnlyNoInk) visibleIndex += 1;
          return (
            <StepBody
              key={step.id}
              step={step}
              isFirst={isFirst}
              bodyClassName={WHITEBOARD_TEXT_CLASS}
            />
          );
        })}
      </div>
    </article>
  );
}
