/** Matches backend `User.role` (including legacy `parent`). */
export type AppUserRole =
  | "admin"
  | "organization"
  | "teacher"
  | "student"
  | "parent";

export function homePathForRole(role: string): string {
  if (role === "admin") return "/admin";
  if (role === "organization") return "/org";
  if (role === "teacher") return "/teacher";
  return "/subjects";
}

export function homePathForAuth(role: string, isInstitution: boolean): string {
  if (role === "admin") return "/admin";
  if (role === "organization") return "/org";
  if (role === "teacher") return "/teacher";
  return isInstitution ? "/dashboard" : "/learn";
}
