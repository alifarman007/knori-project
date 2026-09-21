"use client";

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { ApiError } from "@/lib/api";
import { me as meApi, type Session } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Me, UserSettings } from "@/lib/types";

interface SessionContextValue {
  user: Me | null;
  settings: UserSettings | null;
  loading: boolean;
  /** 401 is not an error to show; anything else is. */
  error: unknown;
  /** Re-read `/me`, e.g. after the name or the timezone changed. */
  refresh: () => Promise<unknown>;
  /** Patch the cached session in place after a settings save. */
  setSettings: (settings: UserSettings) => void;
  setUser: (user: Me) => void;
}

const SessionContext = React.createContext<SessionContextValue | null>(null);

/**
 * Has this person finished onboarding?
 *
 * The column is `users.onboarding_completed_at`, and the API may serialise it as
 * either a boolean or the timestamp. When neither field is present we answer
 * "unknown" and let them through: a wrong `false` would bounce every screen back
 * to `/onboarding` in a loop, which is a far worse failure than a skipped step.
 */
export function onboardingState(user: Me): "complete" | "incomplete" | "unknown" {
  const raw = user as Me & { onboarding_completed_at?: string | null };
  if (typeof raw.onboarding_complete === "boolean") {
    return raw.onboarding_complete ? "complete" : "incomplete";
  }
  if ("onboarding_completed_at" in raw) {
    return raw.onboarding_completed_at ? "complete" : "incomplete";
  }
  return "unknown";
}

function useSessionQuery(): UseQueryResult<Session> {
  return useQuery({
    queryKey: keys.session,
    queryFn: meApi.load,
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && !error.isTransient) return false;
      return failureCount < 2;
    },
  });
}

export interface SessionProviderProps {
  children: React.ReactNode;
  /**
   * Where to send someone who is not signed in. `null` keeps them where they
   * are — the onboarding route does its own thing with an unverified account.
   */
  redirectTo?: string | null;
  /** Send a signed-in user who has not finished onboarding to `/onboarding`. */
  requireOnboarding?: boolean;
  /** Shown while `/me` is in flight. */
  fallback?: React.ReactNode;
}

export function SessionProvider({
  children,
  redirectTo = "/login",
  requireOnboarding = true,
  fallback = null,
}: SessionProviderProps) {
  const query = useSessionQuery();
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();

  const unauthenticated = query.error instanceof ApiError && query.error.isUnauthenticated;
  const user = query.data?.user ?? null;
  const needsOnboarding = Boolean(user && onboardingState(user) === "incomplete");

  React.useEffect(() => {
    if (!unauthenticated || !redirectTo) return;
    // Keep where they were going, so the next sign-in lands there instead of home.
    const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`${redirectTo}${next}`);
  }, [unauthenticated, redirectTo, router, pathname]);

  React.useEffect(() => {
    if (!requireOnboarding || !needsOnboarding) return;
    router.replace("/onboarding");
  }, [requireOnboarding, needsOnboarding, router]);

  const value = React.useMemo<SessionContextValue>(
    () => ({
      user,
      settings: query.data?.settings ?? null,
      loading: query.isPending,
      error: unauthenticated ? null : query.error,
      refresh: () => queryClient.invalidateQueries({ queryKey: keys.session }),
      setSettings: (settings: UserSettings) => {
        queryClient.setQueryData<Session>(keys.session, (current) =>
          current ? { ...current, settings } : current,
        );
      },
      setUser: (next: Me) => {
        queryClient.setQueryData<Session>(keys.session, (current) =>
          current ? { ...current, user: next } : current,
        );
      },
    }),
    [user, query.data?.settings, query.isPending, query.error, unauthenticated, queryClient],
  );

  const hide = query.isPending || unauthenticated || (requireOnboarding && needsOnboarding);

  return (
    <SessionContext.Provider value={value}>{hide ? fallback : children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = React.useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside <SessionProvider>");
  return context;
}

/** The signed-in user, or a throw. Use inside screens the provider already gates. */
export function useUser(): Me {
  const { user } = useSession();
  if (!user) throw new Error("useUser called outside an authenticated screen");
  return user;
}
