"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  ClipboardList,
  GraduationCap,
  LayoutDashboard,
  Library,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

type Props = {
  onNavigate?: () => void;
  className?: string;
  linkClassName?: string;
};

export function AppNavLinks({ onNavigate, className, linkClassName }: Props) {
  const pathname = usePathname();
  const { isInstitution } = useAuth();

  const learnLabel = isInstitution ? "Classes & subjects" : "Explore subjects";
  const modeLabel = isInstitution ? "Teacher-based learning" : "Free learning";
  const links = [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/subjects", label: learnLabel, icon: Library },
    ...(isInstitution
      ? [{ href: "/classroom", label: "Classroom sessions", icon: Users }]
      : []),
    { href: "/learn", label: modeLabel, icon: GraduationCap },
    { href: "/assignments", label: "Assignments", icon: ClipboardList },
    { href: "/detailed-notes", label: "Detailed notes", icon: BookOpen },
  ];

  return (
    <nav className={cn("flex w-full flex-col gap-0.5", className)}>
      {links.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-50"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100",
              linkClassName
            )}
          >
            <Icon className="size-4 shrink-0 opacity-70" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
