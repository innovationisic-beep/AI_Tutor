import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Top-right whiteboard icon column (slot 0 = top: My notes → concept check → concept notes). */
const WHITEBOARD_FLOAT_RIGHT = "right-4 md:right-5";
const WHITEBOARD_FLOAT_TOP_SLOTS = [
  "top-7 md:top-8",
  "top-[5.5rem]",
  "top-[9.25rem]",
  "top-[13rem]",
  "top-[16.75rem]",
] as const;

export function whiteboardFloatIconPosition(slot: number): string {
  const idx = Math.min(
    Math.max(0, slot),
    WHITEBOARD_FLOAT_TOP_SLOTS.length - 1
  );
  return `${WHITEBOARD_FLOAT_RIGHT} ${WHITEBOARD_FLOAT_TOP_SLOTS[idx]}`;
}
