"use client";

import Link from "next/link";
import { Menu, LogOut } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { AppNavDrawer } from "@/components/layout/AppNavDrawer";
import { useLearnSessionChrome } from "@/lib/learning/LearnSessionChrome";
import { SessionProgressionIndicator } from "@/components/learning/SessionProgressionBanner";
import { cn } from "@/lib/utils";

function initials(email: string | undefined) {
  if (!email) return "?";
  const p = email.split("@")[0] ?? "";
  return p.slice(0, 2).toUpperCase() || "?";
}

type Props = {
  /** Immersive learn session: hide sidebar, show menu on all screen sizes. */
  immersive?: boolean;
};

export function Topbar({ immersive = false }: Props) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const chrome = useLearnSessionChrome();

  return (
    <>
      <header
        className={cn(
          "sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-slate-200/80 bg-white/90 px-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90 md:px-5",
          immersive && "relative"
        )}
      >
        <div
          className={cn(
            "flex min-w-0 shrink-0 items-center gap-2",
            !immersive && "md:hidden"
          )}
        >
          <Button
            variant="ghost"
            size="icon"
            type="button"
            aria-label="Open menu"
            onClick={() => setOpen((o) => !o)}
          >
            <Menu className="size-5" />
          </Button>
          <Link
            href="/dashboard"
            className="shrink-0 font-semibold tracking-tight text-slate-900 dark:text-slate-100"
          >
            AI Tutor
          </Link>
          {immersive && chrome?.planProgression ? (
            <SessionProgressionIndicator
              progression={chrome.planProgression}
              variant="compact"
            />
          ) : null}
        </div>
        {immersive && (chrome?.clusterLabel || chrome?.conceptLabel) ? (
          <div className="pointer-events-none absolute left-1/2 flex max-w-[min(320px,52vw)] -translate-x-1/2 flex-col items-center gap-0.5 px-2 text-center">
            {chrome.clusterLabel ? (
              <span className="truncate text-xs font-semibold text-purple-600 dark:text-purple-400">
                {chrome.clusterLabel}
              </span>
            ) : null}
            {chrome.conceptLabel ? (
              <span
                className="truncate text-sm font-medium text-slate-800 dark:text-slate-200"
                title={chrome.conceptLabel}
              >
                {chrome.conceptLabel}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-3">
          {immersive ? (
            <Button variant="outline" size="sm" asChild className="hidden sm:inline-flex">
              <Link href="/subjects">Leave session</Link>
            </Button>
          ) : null}
          <span className="hidden max-w-[180px] truncate text-sm text-slate-600 dark:text-slate-400 lg:inline xl:max-w-[220px]">
            {user?.email ?? "…"}
          </span>
          <Avatar className="h-9 w-9">
            <AvatarFallback>{initials(user?.email)}</AvatarFallback>
          </Avatar>
          <Button variant="outline" size="sm" type="button" onClick={() => logout()}>
            <LogOut className="size-4 shrink-0 opacity-70" />
            <span className="hidden sm:inline">Logout</span>
          </Button>
        </div>
      </header>
      {immersive ? (
        <AppNavDrawer
          open={open}
          onClose={() => setOpen(false)}
          desktop
        />
      ) : (
        <div className="md:hidden">
          <AppNavDrawer open={open} onClose={() => setOpen(false)} />
        </div>
      )}
    </>
  );
}
