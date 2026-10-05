"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { homePathForAuth } from "@/lib/authRedirects";

export default function HomePage() {
  const router = useRouter();
  const { ready, isAuthenticated, user, isInstitution } = useAuth();

  useEffect(() => {
    if (!ready) return;
    if (isAuthenticated && user) {
      router.replace(homePathForAuth(user.role, isInstitution));
    }
    else if (!isAuthenticated) router.replace("/auth/login");
  }, [ready, isAuthenticated, user, isInstitution, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
      <p className="text-sm text-slate-500">Loading…</p>
    </div>
  );
}
