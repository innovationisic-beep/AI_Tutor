"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { homePathForAuth } from "@/lib/authRedirects";
import { getMe, login as apiLogin } from "@/lib/api";
import type { MeResponse, OrganizationBrief, UserMe } from "@/lib/types";

const TOKEN_KEY = "ai_tutor_token";

type AuthContextValue = {
  token: string | null;
  user: UserMe | null;
  organization: OrganizationBrief | null;
  isInstitution: boolean;
  ready: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

function applyMePayload(
  me: MeResponse,
  setUser: (u: UserMe | null) => void,
  setOrganization: (o: OrganizationBrief | null) => void,
  setIsInstitution: (v: boolean) => void
) {
  setUser(me.user);
  setOrganization(me.organization ?? null);
  setIsInstitution(Boolean(me.is_institution));
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserMe | null>(null);
  const [organization, setOrganization] = useState<OrganizationBrief | null>(
    null
  );
  const [isInstitution, setIsInstitution] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const t = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
    setToken(t);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready || !token) {
      if (!token) {
        setUser(null);
        setOrganization(null);
        setIsInstitution(false);
      }
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = await getMe(token);
        if (!cancelled) applyMePayload(me, setUser, setOrganization, setIsInstitution);
      } catch {
        if (!cancelled) {
          localStorage.removeItem(TOKEN_KEY);
          setToken(null);
          setUser(null);
          setOrganization(null);
          setIsInstitution(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin(email, password);
      const accessToken = res.token ?? res.access_token;
      localStorage.setItem(TOKEN_KEY, accessToken);
      setToken(accessToken);
      const me = await getMe(accessToken);
      applyMePayload(me, setUser, setOrganization, setIsInstitution);
      router.replace(homePathForAuth(me.user.role, Boolean(me.is_institution)));
    },
    [router]
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setOrganization(null);
    setIsInstitution(false);
    router.replace("/auth/login");
  }, [router]);

  useEffect(() => {
    const onAuthExpired = () => {
      if (!localStorage.getItem(TOKEN_KEY)) return;
      logout();
    };
    window.addEventListener("ai-tutor:auth-expired", onAuthExpired);
    return () => window.removeEventListener("ai-tutor:auth-expired", onAuthExpired);
  }, [logout]);

  const value = useMemo(
    () => ({
      token,
      user,
      organization,
      isInstitution,
      ready,
      isAuthenticated: Boolean(token),
      login,
      logout,
    }),
    [token, user, organization, isInstitution, ready, login, logout]
  );

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
