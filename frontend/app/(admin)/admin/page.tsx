"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  listOrganizations,
  patchAdminOrganizationStatus,
} from "@/lib/api";
import type { AdminOrganizationRow, AdminOrgStatus } from "@/lib/types";
import { useAuth } from "@/hooks/useAuth";
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

export default function AdminHomePage() {
  const { token, ready, user } = useAuth();
  const [orgs, setOrgs] = useState<AdminOrganizationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || user?.role !== "admin") return;
    setLoading(true);
    setError(null);
    try {
      const list = await listOrganizations(token);
      setOrgs(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load organizations");
    } finally {
      setLoading(false);
    }
  }, [token, user?.role]);

  useEffect(() => {
    if (!ready || !token || user?.role !== "admin") return;
    void load();
  }, [ready, token, user?.role, load]);

  async function setStatus(orgId: string, next: AdminOrgStatus) {
    if (!token) return;
    setActionId(orgId);
    setError(null);
    try {
      const updated = await patchAdminOrganizationStatus(token, orgId, next);
      setOrgs((prev) =>
        prev.map((o) => (o.id === orgId ? { ...o, status: updated.status } : o))
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setActionId(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
            Organizations
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Institution tenants, plans, and invite codes.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/admin/curriculum">Curriculum builder</Link>
          </Button>
          <Button asChild>
            <Link href="/admin/create-organization">Create organization</Link>
          </Button>
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:p-6">
        {error ? (
          <p className="mb-4 text-sm text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        ) : null}
        {loading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : orgs.length === 0 ? (
          <p className="text-sm text-slate-500">
            No organizations yet.{" "}
            <Link
              href="/admin/create-organization"
              className="font-medium text-blue-600 underline-offset-4 hover:underline dark:text-blue-400"
            >
              Create one
            </Link>
            .
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Name
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Plan
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Status
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Max students
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Max teachers
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Invite code
                  </th>
                  <th className="pb-3 pr-4 font-medium text-slate-700 dark:text-slate-300">
                    Created
                  </th>
                  <th className="pb-3 font-medium text-slate-700 dark:text-slate-300">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((o) => (
                  <tr
                    key={o.id}
                    className="border-b border-slate-100 dark:border-slate-800"
                  >
                    <td className="py-3 pr-4 font-medium text-slate-900 dark:text-slate-100">
                      {o.name}
                    </td>
                    <td className="py-3 pr-4 capitalize text-slate-700 dark:text-slate-300">
                      {o.subscription_plan}
                    </td>
                    <td className="py-3 pr-4">
                      <span
                        className={
                          o.status === "active"
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-slate-500 dark:text-slate-400"
                        }
                      >
                        {o.status === "active" ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="py-3 pr-4 tabular-nums text-slate-700 dark:text-slate-300">
                      {o.max_students}
                    </td>
                    <td className="py-3 pr-4 tabular-nums text-slate-700 dark:text-slate-300">
                      {o.max_teachers}
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs text-slate-800 dark:text-slate-200">
                      {o.invite_code ?? "—"}
                    </td>
                    <td className="py-3 pr-4 whitespace-nowrap text-slate-600 dark:text-slate-400">
                      {formatDate(o.created_at)}
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <Link href={`/admin/organization/${o.id}`}>View</Link>
                        </Button>
                        {o.status === "active" ? (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={actionId === o.id}
                            onClick={() => void setStatus(o.id, "inactive")}
                          >
                            {actionId === o.id ? "…" : "Deactivate"}
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={actionId === o.id}
                            onClick={() => void setStatus(o.id, "active")}
                          >
                            {actionId === o.id ? "…" : "Activate"}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Link
        href="/"
        className="inline-block text-sm font-medium text-blue-600 underline-offset-4 hover:underline dark:text-blue-400"
      >
        Home
      </Link>
    </div>
  );
}
