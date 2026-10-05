"use client";

import Link from "next/link";
import { AppNavLinks } from "@/components/layout/AppNavLinks";

export function Sidebar() {
  return (
    <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200/80 bg-white/80 backdrop-blur md:flex md:min-h-screen dark:border-slate-800 dark:bg-slate-950/80">
      <div className="flex h-14 shrink-0 items-center border-b border-slate-200/80 px-4 dark:border-slate-800">
        <Link
          href="/dashboard"
          className="font-semibold tracking-tight text-slate-900 dark:text-slate-100"
        >
          AI Tutor
        </Link>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 p-2">
        <AppNavLinks />
      </nav>
    </aside>
  );
}
