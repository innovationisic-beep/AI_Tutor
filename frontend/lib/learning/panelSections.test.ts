import { describe, expect, it } from "vitest";

import type { PlanProgressionView } from "@/lib/types";

import {
  activeSessionHeading,
  completedSessionHeading,
  flattenNotesSections,
  flattenThreadSections,
} from "./panelSections";

const progressionAfterS2Start: PlanProgressionView = {
  completion_percentage: 50,
  status: "in_progress",
  learning_path: [
    {
      session_plan_id: "s1",
      sequence_number: 1,
      title: "Introduction",
      state: "completed",
    },
    {
      session_plan_id: "s2",
      sequence_number: 2,
      title: "Deep dive",
      state: "active",
    },
    {
      session_plan_id: "s3",
      sequence_number: 3,
      title: "Review",
      state: "locked",
    },
  ],
  last_transition: {
    kind: "session_started",
    title: "SESSION 2 STARTED",
    subtitle: "Zone 1 • Cluster A",
    session_plan_id: "s2",
    sequence_number: 2,
  },
};

describe("panelSections session headings", () => {
  it("labels archived content with the completed session, not the new one", () => {
    expect(completedSessionHeading(progressionAfterS2Start)).toBe(
      "Session 1: Introduction"
    );
  });

  it("labels live content with the active session", () => {
    expect(activeSessionHeading(progressionAfterS2Start)).toBe(
      "Session 2: Deep dive"
    );
  });

  it("falls back to sequence before last_transition when snapshot lags", () => {
    const lagging: PlanProgressionView = {
      ...progressionAfterS2Start,
      learning_path: progressionAfterS2Start.learning_path.map((row) =>
        row.sequence_number === 1
          ? { ...row, state: "active" }
          : row
      ),
    };
    expect(completedSessionHeading(lagging)).toBe("Session 1: Introduction");
  });

  it("shows Session 1 heading for first-session panel content", () => {
    const s1Only: PlanProgressionView = {
      completion_percentage: 0,
      status: "in_progress",
      learning_path: [
        {
          session_plan_id: "s1",
          sequence_number: 1,
          title: "Introduction",
          state: "active",
        },
      ],
    };
    const thread = flattenThreadSections(
      [],
      [],
      activeSessionHeading(s1Only),
      [{ id: "q-0", kind: "question", text: "What?" }],
      (id, heading) => ({ id, kind: "section", heading })
    );
    expect(thread[0]).toMatchObject({
      kind: "section",
      heading: "Session 1: Introduction",
    });
  });

  it("shows Session 1 heading on first-session notes", () => {
    const s1Only: PlanProgressionView = {
      completion_percentage: 0,
      status: "in_progress",
      learning_path: [
        {
          session_plan_id: "s1",
          sequence_number: 1,
          title: "Introduction",
          state: "active",
        },
      ],
    };
    const sections = flattenNotesSections(
      [],
      activeSessionHeading(s1Only),
      [{ conceptName: "Photosynthesis", markdown: "Notes here" }]
    );
    expect(sections).toHaveLength(1);
    expect(sections[0].heading).toBe("Session 1: Introduction");
  });
});
