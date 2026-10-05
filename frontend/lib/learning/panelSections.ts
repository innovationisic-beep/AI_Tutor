import type { PlanProgressionView } from "@/lib/types";

export type PanelSection<T> = {
  id: string;
  heading: string;
  items: T[];
};

export type NotesPanelSection = {
  id: string;
  heading: string;
  entries: { conceptName: string; markdown: string }[];
};

export function sessionHeadingFromPlan(
  progression: PlanProgressionView | null | undefined,
  sequenceNumber: number
): string {
  const row = progression?.learning_path?.find(
    (p) => p.sequence_number === sequenceNumber
  );
  if (row?.title?.trim()) {
    return `Session ${sequenceNumber}: ${row.title.trim()}`;
  }
  return `Session ${sequenceNumber}`;
}

export function completedSessionHeading(
  progression: PlanProgressionView | null | undefined
): string {
  const completedRows = (progression?.learning_path ?? []).filter(
    (p) => p.state === "completed"
  );
  if (completedRows.length > 0) {
    const latestCompleted = completedRows.reduce((a, b) =>
      a.sequence_number >= b.sequence_number ? a : b
    );
    return sessionHeadingFromPlan(progression, latestCompleted.sequence_number);
  }

  const transition = progression?.last_transition;
  if (
    transition?.kind === "session_started" &&
    typeof transition.sequence_number === "number" &&
    transition.sequence_number > 1
  ) {
    return sessionHeadingFromPlan(
      progression,
      transition.sequence_number - 1
    );
  }
  if (transition?.title?.trim() && transition.kind !== "session_started") {
    return transition.title.trim();
  }
  return "Previous session";
}

export function activeSessionHeading(
  progression: PlanProgressionView | null | undefined
): string {
  const active = progression?.learning_path?.find((p) => p.state === "active");
  if (active) {
    return sessionHeadingFromPlan(progression, active.sequence_number);
  }
  return "Current session";
}

export function clusterSectionHeading(
  clusterIndex: number,
  clusterName?: string | null
): string {
  const n = clusterIndex + 1;
  const name = clusterName?.trim();
  return name ? `Cluster ${n}: ${name}` : `Cluster ${n}`;
}

/** Flatten archived sections plus optional current-session heading into display thread. */
function withPrefixedIds<T extends { id: string }>(
  items: T[],
  prefix: string
): T[] {
  return items.map((item) => ({
    ...item,
    id: `${prefix}::${item.id}`,
  }));
}

export { withPrefixedIds };

export function flattenThreadSections<
  T extends { id: string; kind: string },
  H extends T,
>(
  sessionSections: PanelSection<T>[],
  withinSessionSections: PanelSection<T>[],
  currentHeading: string | null,
  currentItems: T[],
  makeSectionItem: (id: string, heading: string) => H
): T[] {
  const out: T[] = [];
  for (const section of sessionSections) {
    if (section.items.length === 0) continue;
    out.push(makeSectionItem(section.id, section.heading));
    out.push(...withPrefixedIds(section.items, section.id));
  }
  const hasCurrentContent =
    withinSessionSections.some((s) => s.items.length > 0) ||
    currentItems.length > 0;
  if (hasCurrentContent && currentHeading) {
    out.push(makeSectionItem("current-session", currentHeading));
  }
  for (const section of withinSessionSections) {
    if (section.items.length === 0) continue;
    out.push(makeSectionItem(section.id, section.heading));
    out.push(...withPrefixedIds(section.items, section.id));
  }
  const livePrefix =
    sessionSections.length > 0 || withinSessionSections.length > 0
      ? "live"
      : null;
  out.push(
    ...(livePrefix
      ? withPrefixedIds(currentItems, livePrefix)
      : currentItems)
  );
  return out;
}

export function flattenNotesSections(
  sessionSections: NotesPanelSection[],
  currentHeading: string | null,
  currentEntries: NotesPanelSection["entries"]
): NotesPanelSection[] {
  const out: NotesPanelSection[] = [...sessionSections];
  if (currentEntries.length === 0) return out;
  out.push({
    id: "current-session-notes",
    heading: currentHeading ?? "",
    entries: currentEntries,
  });
  return out;
}
