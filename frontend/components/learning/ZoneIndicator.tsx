import { cn } from "@/lib/utils";

type ZoneConfig = {
  label: string;
  sublabel: string;
  dot: string;
  badge: string;
  text: string;
};

const ZONE_CONFIG: Record<number, ZoneConfig> = {
  0: {
    label: "🟡 Zone 0: Opening",
    sublabel: "Curiosity & prerequisites",
    dot: "bg-amber-400",
    badge:
      "border-amber-200/80 bg-amber-50/70 dark:border-amber-800/60 dark:bg-amber-950/30",
    text: "text-amber-800 dark:text-amber-300",
  },
  1: {
    label: "🟢 Zone 1: Learning",
    sublabel: "Main teaching",
    dot: "bg-emerald-500",
    badge:
      "border-emerald-200/80 bg-emerald-50/70 dark:border-emerald-800/60 dark:bg-emerald-950/30",
    text: "text-emerald-800 dark:text-emerald-300",
  },
  2: {
    label: "🟡 Zone 2: Deep thinking",
    sublabel: "Why / how",
    dot: "bg-blue-500",
    badge:
      "border-blue-200/80 bg-blue-50/70 dark:border-blue-800/60 dark:bg-blue-950/30",
    text: "text-blue-800 dark:text-blue-300",
  },
  3: {
    label: "🔴 Zone 3: Challenge",
    sublabel: "Scenarios & problems",
    dot: "bg-violet-500",
    badge:
      "border-violet-200/80 bg-violet-50/70 dark:border-violet-800/60 dark:bg-violet-950/30",
    text: "text-violet-800 dark:text-violet-300",
  },
  4: {
    label: "🟣 Zone 4: Reflection",
    sublabel: "Extension & discussion",
    dot: "bg-slate-700 dark:bg-slate-400",
    badge:
      "border-slate-300/80 bg-slate-100/70 dark:border-slate-600/60 dark:bg-slate-800/50",
    text: "text-slate-800 dark:text-slate-200",
  },
};

const FALLBACK: ZoneConfig = ZONE_CONFIG[0];

type Props = {
  zone: number;
  className?: string;
};

export function ZoneIndicator({ zone, className }: Props) {
  const cfg = ZONE_CONFIG[zone] ?? FALLBACK;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        cfg.badge,
        cfg.text,
        className
      )}
      title={`${cfg.label} — ${cfg.sublabel}`}
    >
      <span
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", cfg.dot)}
        aria-hidden="true"
      />
      <span>{cfg.label}</span>
      <span className="opacity-70">— {cfg.sublabel}</span>
    </span>
  );
}
