"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

export default function AdminShellLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { ready, isAuthenticated, user, logout } = useAuth();

  useEffect(() => {
    if (!ready) return;
    if (!isAuthenticated) router.replace("/auth/login");
  }, [ready, isAuthenticated, router]);

  useEffect(() => {
    if (!ready || !isAuthenticated || !user) return;
    if (user.role !== "admin") router.replace("/");
  }, [ready, isAuthenticated, user, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  if (!isAuthenticated || !user || user.role !== "admin") {
    return null;
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900 md:px-8">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3">
          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Admin panel
          </span>
          <nav className="flex flex-wrap items-center gap-3 text-sm">
            <Link
              href="/"
              className="text-slate-600 underline-offset-4 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-slate-100"
            >
              Home
            </Link>
            <Link
              href="/auth/login"
              className="text-slate-600 underline-offset-4 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-slate-100"
            >
              Login
            </Link>
            <Link
              href="/auth/signup"
              className="text-slate-600 underline-offset-4 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-slate-100"
            >
              Sign up
            </Link>
            <button
              type="button"
              onClick={() => logout()}
              className="rounded-lg bg-slate-200 px-3 py-1.5 font-medium text-slate-900 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-100 dark:hover:bg-slate-600"
            >
              Log out
            </button>
          </nav>
        </div>
      </header>
      <div className="px-4 py-8 md:px-8">{children}</div>
    </div>
  );
}
