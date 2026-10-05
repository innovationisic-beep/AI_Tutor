"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { homePathForAuth } from "@/lib/authRedirects";
import { getOrgByInviteCode, register as apiRegister } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Individual learner signup: numeric grades 1–12 (stored as string, e.g. "7"). */
const INDIVIDUAL_GRADES = [
  "1",
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "10",
  "11",
  "12",
] as const;
const STYLES = ["visual", "practical", "theory", "mixed"] as const;

type SignupMode = "individual" | "organization";

export default function SignupPage() {
  const router = useRouter();
  const { ready, isAuthenticated, user, isInstitution } = useAuth();
  const [signupMode, setSignupMode] = useState<SignupMode>("individual");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [grade, setGrade] =
    useState<(typeof INDIVIDUAL_GRADES)[number]>("6");
  const [interests, setInterests] = useState("");
  const [preferredTeachingStyle, setPreferredTeachingStyle] =
    useState<(typeof STYLES)[number]>("mixed");

  const [inviteCode, setInviteCode] = useState("");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [orgPreview, setOrgPreview] = useState<{
    organization_name: string;
    classes: { id: string; name: string }[];
  } | null>(null);
  const [classId, setClassId] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!ready) return;
    if (isAuthenticated && user) {
      router.replace(homePathForAuth(user.role, isInstitution));
    }
  }, [ready, isAuthenticated, user, isInstitution, router]);

  useEffect(() => {
    if (signupMode !== "organization") {
      setOrgPreview(null);
      setInviteError(null);
      setInviteLoading(false);
      setInviteCode("");
      setClassId("");
      return;
    }

    const raw = inviteCode.trim().toUpperCase();
    if (raw.length < 6) {
      setOrgPreview(null);
      setInviteError(null);
      setInviteLoading(false);
      return;
    }

    const t = setTimeout(() => {
      void (async () => {
        setInviteLoading(true);
        setInviteError(null);
        try {
          const data = await getOrgByInviteCode(raw);
          setOrgPreview(data);
          setClassId("");
        } catch (e) {
          setOrgPreview(null);
          setClassId("");
          setInviteError(
            e instanceof Error ? e.message : "Could not verify invite code"
          );
        } finally {
          setInviteLoading(false);
        }
      })();
    }, 400);

    return () => clearTimeout(t);
  }, [inviteCode, signupMode]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const nm = name.trim();
    const em = email.trim();
    if (!nm || !em || !password) {
      setError("Enter name, email, and password.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setSubmitting(true);
    try {
      if (signupMode === "individual") {
        await apiRegister({
          account_type: "individual",
          name: nm,
          email: em,
          password,
          grade,
          interests: interests.trim() || undefined,
          preferred_teaching_style: preferredTeachingStyle,
        });
      } else {
        const code = inviteCode.trim().toUpperCase();
        if (!code || code.length < 6) {
          setError("Enter a valid school invite code.");
          setSubmitting(false);
          return;
        }
        if (!orgPreview) {
          setError("Verify your invite code before continuing.");
          setSubmitting(false);
          return;
        }
        if (!classId) {
          setError("Select your class.");
          setSubmitting(false);
          return;
        }
        await apiRegister({
          account_type: "organization",
          name: nm,
          email: em,
          password,
          invite_code: code,
          class_id: classId,
        });
      }
      router.push("/auth/login?registered=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader>
          <CardTitle className="text-2xl">Create account</CardTitle>
          <CardDescription>
            Sign up as an independent learner or join your school with a code
            from your admin.
          </CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit}>
          <CardContent className="space-y-5">
            {error ? (
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            ) : null}

            <div className="space-y-2">
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                How do you want to learn?
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setSignupMode("individual")}
                  disabled={submitting}
                  className={cn(
                    "rounded-lg border px-3 py-3 text-left text-sm transition",
                    signupMode === "individual"
                      ? "border-slate-900 bg-slate-100 dark:border-slate-100 dark:bg-slate-800"
                      : "border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-900"
                  )}
                >
                  <span className="font-medium">Learn individually</span>
                  <span className="mt-1 block text-xs text-slate-600 dark:text-slate-400">
                    Personal workspace & curriculum
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setSignupMode("organization")}
                  disabled={submitting}
                  className={cn(
                    "rounded-lg border px-3 py-3 text-left text-sm transition",
                    signupMode === "organization"
                      ? "border-slate-900 bg-slate-100 dark:border-slate-100 dark:bg-slate-800"
                      : "border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-900"
                  )}
                >
                  <span className="font-medium">Join a school</span>
                  <span className="mt-1 block text-xs text-slate-600 dark:text-slate-400">
                    Invite code from your school
                  </span>
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={submitting}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                required
                minLength={8}
              />
            </div>

            {signupMode === "individual" ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="grade">Grade</Label>
                  <select
                    id="grade"
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800"
                    value={grade}
                    onChange={(e) =>
                      setGrade(
                        e.target.value as (typeof INDIVIDUAL_GRADES)[number]
                      )
                    }
                    disabled={submitting}
                  >
                    {INDIVIDUAL_GRADES.map((g) => (
                      <option key={g} value={g}>
                        Grade {g}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="interests">Interests (optional)</Label>
                  <Input
                    id="interests"
                    value={interests}
                    onChange={(e) => setInterests(e.target.value)}
                    disabled={submitting}
                    placeholder="e.g. robotics, football, art"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="preferred_teaching_style">
                    Preferred teaching style
                  </Label>
                  <select
                    id="preferred_teaching_style"
                    className="flex h-10 w-full rounded-md border border-slate-200 bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800"
                    value={preferredTeachingStyle}
                    onChange={(e) =>
                      setPreferredTeachingStyle(
                        e.target.value as (typeof STYLES)[number]
                      )
                    }
                    disabled={submitting}
                  >
                    {STYLES.map((s) => (
                      <option key={s} value={s}>
                        {s[0].toUpperCase() + s.slice(1)}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="invite_code">School invite code</Label>
                  <Input
                    id="invite_code"
                    value={inviteCode}
                    onChange={(e) =>
                      setInviteCode(e.target.value.toUpperCase())
                    }
                    disabled={submitting}
                    placeholder="e.g. ABC123"
                    autoComplete="off"
                    className="font-mono uppercase"
                  />
                  {inviteLoading ? (
                    <p className="text-xs text-slate-500">Checking code…</p>
                  ) : null}
                  {inviteError && !inviteLoading ? (
                    <p className="text-xs text-red-600 dark:text-red-400">
                      {inviteError}
                    </p>
                  ) : null}
                  {orgPreview && !inviteLoading ? (
                    <p className="text-sm text-emerald-700 dark:text-emerald-300">
                      Joining:{" "}
                      <span className="font-medium">
                        {orgPreview.organization_name}
                      </span>
                    </p>
                  ) : null}
                </div>
                {orgPreview && orgPreview.classes.length > 0 ? (
                  <div className="space-y-2">
                    <Label htmlFor="class_id">Class</Label>
                    <select
                      id="class_id"
                      required
                      className="flex h-10 w-full rounded-md border border-slate-200 bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800"
                      value={classId}
                      onChange={(e) => setClassId(e.target.value)}
                      disabled={submitting}
                    >
                      <option value="">Select your class</option>
                      {orgPreview.classes.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {orgPreview && orgPreview.classes.length === 0 ? (
                  <p className="text-sm text-amber-700 dark:text-amber-300">
                    This school has no classes yet. Ask your administrator to
                    add classes first.
                  </p>
                ) : null}
              </>
            )}
          </CardContent>
          <CardFooter className="flex flex-col gap-4">
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Creating..." : "Create account"}
            </Button>
            <p className="text-center text-sm text-slate-600 dark:text-slate-400">
              Already have an account?{" "}
              <Link
                href="/auth/login"
                className="font-medium text-slate-900 underline underline-offset-4 dark:text-slate-200"
              >
                Sign in
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
