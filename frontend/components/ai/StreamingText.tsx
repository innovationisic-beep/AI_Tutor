"use client";

type StreamingTextProps = {
  text: string;
  className?: string;
};

/** Renders full text immediately (no staged reveal). */
export function StreamingText({ text, className }: StreamingTextProps) {
  return <p className={className}>{text}</p>;
}
