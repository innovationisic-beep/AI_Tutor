/** Speak-only beats must not reveal spoken text as durable board ink. */

export function visualTeachingDisplayText(
  boardWrites: readonly { text?: string }[] | null | undefined
): string | undefined {
  if (boardWrites && boardWrites.length > 0) return undefined;
  return "";
}
