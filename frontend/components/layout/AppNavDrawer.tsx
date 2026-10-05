"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { AppNavLinks } from "@/components/layout/AppNavLinks";

type Props = {
  open: boolean;
  onClose: () => void;
  /** When true, drawer works on desktop too (immersive learn mode). */
  desktop?: boolean;
};

export function AppNavDrawer({ open, onClose, desktop = false }: Props) {
  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-30 bg-black/40",
          open ? "block" : "hidden",
          !desktop && "md:hidden"
        )}
        aria-hidden
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-slate-200 bg-white shadow-lg transition-transform dark:border-slate-800 dark:bg-slate-950",
          open ? "translate-x-0" : "-translate-x-full",
          !desktop && "md:hidden"
        )}
      >
        <div className="flex h-14 items-center border-b border-slate-200/80 px-4 dark:border-slate-800">
          <Link
            href="/dashboard"
            className="font-semibold tracking-tight text-slate-900 dark:text-slate-100"
            onClick={onClose}
          >
            AI Tutor
          </Link>
        </div>
        <div className="p-2">
          <AppNavLinks onNavigate={onClose} />
        </div>
      </aside>
    </>
  );
}
