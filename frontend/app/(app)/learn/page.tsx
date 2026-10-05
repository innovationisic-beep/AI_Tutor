"use client";

import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function LearnModePage() {
  const { isInstitution } = useAuth();

  return (
    <div className="w-full max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {isInstitution ? "Teacher-based learning" : "Free learning"}
        </h1>
        <p className="mt-1 text-slate-600 dark:text-slate-400">
          {isInstitution
            ? "Use your class and teacher-defined subject flow."
            : "Explore and learn at your own pace with the admin curriculum."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {isInstitution ? "Continue with class subjects" : "Start exploring subjects"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link href="/subjects">
              {isInstitution ? "Open classes & subjects" : "Explore subjects"}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
