"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";
import { homePathForRole } from "@/lib/authRedirects";
import { LearnSessionChromeProvider } from "@/lib/learning/LearnSessionChrome";
import { cn } from "@/lib/utils";

export default function AppShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { ready, isAuthenticated, user } = useAuth();
  const isImmersiveLearn = /^\/learn\/[^/]+/.test(pathname ?? "");

  useEffect(() => {
    if (!ready) return;
    if (!isAuthenticated) router.replace("/auth/login");
  }, [ready, isAuthenticated, router]);

  useEffect(() => {
    if (!ready || !user) return;
    const r = user.role;
    if (r === "admin" || r === "organization" || r === "teacher") {
      router.replace(homePathForRole(r));
    }
  }, [ready, user, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  if (user.role === "admin" || user.role === "organization" || user.role === "teacher") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  const shell = (
    <>
      {!isImmersiveLearn ? <Sidebar /> : null}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Topbar immersive={isImmersiveLearn} />
        <main
          className={cn(
            "flex min-h-0 flex-1 flex-col",
            isImmersiveLearn ? "overflow-hidden p-0" : "px-4 py-6 md:px-8"
          )}
        >
          {children}
        </main>
      </div>
    </>
  );

  return (
    <div
      className={cn(
        "flex w-full bg-slate-50 dark:bg-slate-950",
        isImmersiveLearn ? "h-screen max-h-screen min-h-0" : "min-h-screen"
      )}
    >
      {isImmersiveLearn ? (
        <LearnSessionChromeProvider>{shell}</LearnSessionChromeProvider>
      ) : (
        shell
      )}
    </div>
  );
}
