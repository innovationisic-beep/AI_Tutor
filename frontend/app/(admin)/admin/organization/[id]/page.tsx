"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { getAdminOrganization } from "@/lib/api";
import type { AdminOrganizationDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export default function AdminOrganizationViewPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const { token, ready, user } = useAuth();
  const [org, setOrg] = useState<AdminOrganizationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !id || user?.role !== "admin") return;
    setLoading(true);
    setError(null);
    try {
      const row = await getAdminOrganization(token, id);
      setOrg(row);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setOrg(null);
    } finally {
      setLoading(false);
    }
  }, [token, id, user?.role]);

  useEffect(() => {
    if (!ready || !token || user?.role !== "admin" || !id) return;
    void load();
  }, [ready, token, user?.role, id, load]);

  if (!ready || user?.role !== "admin") {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="text-sm text-slate-500">Loading organization…</p>
      </div>
    );
  }

  if (error || !org) {
    return (
      <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Not found"}</p>
        <Button variant="outline" asChild>
          <Link href="/admin">Back to list</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">
          {org.name}
        </h1>
        <Button variant="outline" size="sm" asChild>
          <Link href="/admin">← Organizations</Link>
        </Button>
      </div>

      <dl className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Plan</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.subscription_plan}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Status</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.status === "active" ? "Active" : "Inactive"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">
            Max students
          </dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.max_students}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">
            Max teachers
          </dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.max_teachers}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs font-medium uppercase text-slate-500">
            Invite code
          </dt>
          <dd className="mt-1 font-mono text-lg tracking-wider text-slate-900 dark:text-slate-100">
            {org.invite_code ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Contact</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.contact_email ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Type</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {org.organization_type}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Created</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {formatDate(org.created_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Updated</dt>
          <dd className="mt-1 text-slate-900 dark:text-slate-100">
            {formatDate(org.updated_at)}
          </dd>
        </div>
      </dl>
    </div>
  );
}
