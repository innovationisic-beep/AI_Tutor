import type { TutorResponse } from "@/lib/types";

/**
 * Explicit continue ack from the backend — pending cleared; timeline may resume.
 * Treats missing outcome as success when the type is authoritative.
 */
export function isFlowCheckpointContinueAck(
  tutor: TutorResponse | null | undefined,
): boolean {
  if (!tutor || tutor.type !== "flow_checkpoint_continue_ack") return false;
  const outcome = tutor.outcome;
  if (outcome == null || outcome === "") return true;
  return outcome === "accepted" || outcome === "already_cleared";
}

/** Overlay body for a checkpoint question. Teachback text and stale replies are rejected. */
export function acceptedCheckpointClarification(
  tutor: { type?: string; message?: string; outcome?: string } | null | undefined,
): string | null {
  if (!tutor || tutor.type !== "flow_checkpoint_clarification") return null;
  if (tutor.outcome === "stale") return null;
  const msg = (tutor.message ?? "").trim();
  return msg || "Hope that clears your confusion.";
}
