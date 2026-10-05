"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { createOrganization } from "@/lib/api";
import type { AdminOrganizationCreated, AdminOrgPlan, AdminOrgStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { Check, Copy } from "lucide-react";

const PLANS: AdminOrgPlan[] = ["free", "basic", "premium"];

export default function CreateOrganizationPage() {
  const { token, ready, user } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [maxStudents, setMaxStudents] = useState(100);
  const [maxTeachers, setMaxTeachers] = useState(20);
  const [plan, setPlan] = useState<AdminOrgPlan>("free");
  const [orgStatus, setOrgStatus] = useState<AdminOrgStatus>("active");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<AdminOrganizationCreated | null>(null);
  const [copiedInvite, setCopiedInvite] = useState(false);
  const [copiedEmail, setCopiedEmail] = useState(false);

  const validate = useCallback(() => {
    const err: Record<string, string> = {};
    const nm = name.trim();
    if (nm.length < 2) err.name = "Name must be at least 2 characters.";
    const em = email.trim();
    if (!em) err.email = "Email is required for the organization login.";
    if (password.length < 6) {
      err.password = "Password must be at least 6 characters.";
    }
    if (!Number.isFinite(maxStudents) || maxStudents < 1) {
      err.maxStudents = "Max students must be at least 1.";
    }
    if (!Number.isFinite(maxTeachers) || maxTeachers < 0) {
      err.maxTeachers = "Max teachers cannot be negative.";
    }
    setFieldErrors(err);
    return Object.keys(err).length === 0;
  }, [name, email, password, maxStudents, maxTeachers]);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setError(null);
      if (!token || user?.role !== "admin") return;
      if (!validate()) return;
      setSubmitting(true);
      try {
        const result = await createOrganization(token, {
          name: name.trim(),
          email: email.trim(),
          password,
          max_students: maxStudents,
          max_teachers: maxTeachers,
          subscription_plan: plan,
          status: orgStatus,
        });
        setCreated(result);
        setPassword("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Create failed");
      } finally {
        setSubmitting(false);
      }
    },
    [
      token,
      user?.role,
      validate,
      name,
      email,
      password,
      maxStudents,
      maxTeachers,
      plan,
      orgStatus,
    ]
  );

  async function copyInvite() {
    if (!created?.invite_code) return;
    try {
      await navigator.clipboard.writeText(created.invite_code);
      setCopiedInvite(true);
      setTimeout(() => setCopiedInvite(false), 2000);
    } catch {
      setCopiedInvite(false);
    }
  }

  async function copyLoginEmail() {
    if (!created?.login_email) return;
    try {
      await navigator.clipboard.writeText(created.login_email);
      setCopiedEmail(true);
      setTimeout(() => setCopiedEmail(false), 2000);
    } catch {
      setCopiedEmail(false);
    }
  }

  function resetForm() {
    setCreated(null);
    setName("");
    setEmail("");
    setPassword("");
    setMaxStudents(100);
    setMaxTeachers(20);
    setPlan("free");
    setOrgStatus("active");
    setFieldErrors({});
    setError(null);
  }

  if (!ready || user?.role !== "admin") {
    return (
      <div className="mx-auto max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="text-sm text-slate-600 dark:text-slate-400">Loading…</p>
      </div>
    );
  }

  if (created) {
    return (
      <div className="mx-auto max-w-lg space-y-6">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-4 shadow-sm dark:border-emerald-900 dark:bg-emerald-950/40">
          <div className="flex items-start gap-2">
            <Check className="mt-0.5 size-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <div className="space-y-1">
              <p className="font-medium text-emerald-900 dark:text-emerald-100">
                Organization created
              </p>
              <p className="text-sm text-emerald-800 dark:text-emerald-200">
                {created.name}
              </p>
            </div>
          </div>
          <div className="mt-4 space-y-4 rounded-lg border border-emerald-200/80 bg-white p-4 dark:border-emerald-800 dark:bg-slate-950">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Login email
              </p>
              <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-50">
                {created.login_email}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void copyLoginEmail()}
              >
                {copiedEmail ? (
                  "Copied"
                ) : (
                  <>
                    <Copy className="mr-2 size-4" />
                    Copy email
                  </>
                )}
              </Button>
            </div>
            <div className="border-t border-emerald-100 pt-4 dark:border-emerald-900/50">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Invite code
              </p>
              <p className="mt-1 font-mono text-xl font-semibold tracking-wider text-slate-900 dark:text-slate-50">
                {created.invite_code}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => void copyInvite()}
              >
                {copiedInvite ? (
                  "Copied"
                ) : (
                  <>
                    <Copy className="mr-2 size-4" />
                    Copy code
                  </>
                )}
              </Button>
            </div>
          </div>
          <p className="mt-3 text-xs text-emerald-800/90 dark:text-emerald-200/90">
            Share the password you entered with the organization admin separately.
            It is not shown again.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button type="button" variant="outline" onClick={resetForm}>
            Create another
          </Button>
          <Button type="button" asChild variant="default">
            <Link href="/admin">Back to organizations</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          Create organization
        </h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Configure a new institution tenant, manager login, and invite code.
        </p>
      </div>

      <form
        onSubmit={(e) => void onSubmit(e)}
        className="space-y-8 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:p-6"
      >
        {error ? (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        ) : null}

        <div className="space-y-2">
          <Label htmlFor="org-name">Organization name</Label>
          <Input
            id="org-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={submitting}
            minLength={2}
            maxLength={120}
            className={cn(fieldErrors.name && "border-red-500")}
          />
          {fieldErrors.name ? (
            <p className="text-xs text-red-600 dark:text-red-400">
              {fieldErrors.name}
            </p>
          ) : null}
        </div>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Login credentials
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            The organization manager uses this email and password to sign in at
            the same login page as everyone else.
          </p>
          <div className="space-y-2">
            <Label htmlFor="org-email">Email</Label>
            <Input
              id="org-email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              required
              className={cn(fieldErrors.email && "border-red-500")}
            />
            {fieldErrors.email ? (
              <p className="text-xs text-red-600 dark:text-red-400">
                {fieldErrors.email}
              </p>
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor="org-password">Password</Label>
            <Input
              id="org-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              required
              minLength={6}
              className={cn(fieldErrors.password && "border-red-500")}
            />
            {fieldErrors.password ? (
              <p className="text-xs text-red-600 dark:text-red-400">
                {fieldErrors.password}
              </p>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Minimum 6 characters.
              </p>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Limits
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="max-students">Max students</Label>
              <Input
                id="max-students"
                type="number"
                min={1}
                value={maxStudents}
                onChange={(e) => setMaxStudents(Number(e.target.value))}
                disabled={submitting}
                className={cn(fieldErrors.maxStudents && "border-red-500")}
              />
              {fieldErrors.maxStudents ? (
                <p className="text-xs text-red-600 dark:text-red-400">
                  {fieldErrors.maxStudents}
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="max-teachers">Max teachers</Label>
              <Input
                id="max-teachers"
                type="number"
                min={0}
                value={maxTeachers}
                onChange={(e) => setMaxTeachers(Number(e.target.value))}
                disabled={submitting}
                className={cn(fieldErrors.maxTeachers && "border-red-500")}
              />
              {fieldErrors.maxTeachers ? (
                <p className="text-xs text-red-600 dark:text-red-400">
                  {fieldErrors.maxTeachers}
                </p>
              ) : null}
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Subscription plan
          </h2>
          <select
            id="plan"
            className="flex h-10 w-full max-w-xs rounded-md border border-slate-200 bg-transparent px-3 py-2 text-sm dark:border-slate-700"
            value={plan}
            onChange={(e) => setPlan(e.target.value as AdminOrgPlan)}
            disabled={submitting}
          >
            {PLANS.map((p) => (
              <option key={p} value={p}>
                {p[0].toUpperCase() + p.slice(1)}
              </option>
            ))}
          </select>
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Status
          </h2>
          <div className="flex flex-col gap-2 sm:flex-row sm:gap-6">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="org-status"
                checked={orgStatus === "active"}
                onChange={() => setOrgStatus("active")}
                disabled={submitting}
                className="size-4"
              />
              Active
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name="org-status"
                checked={orgStatus === "inactive"}
                onChange={() => setOrgStatus("inactive")}
                disabled={submitting}
                className="size-4"
              />
              Inactive
            </label>
          </div>
        </section>

        <div className="flex flex-wrap gap-3 pt-2">
          <Button type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create organization"}
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link href="/admin">Cancel</Link>
          </Button>
        </div>
      </form>
    </div>
  );
}
