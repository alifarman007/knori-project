"use client";

import * as React from "react";

import { LiveEventsProvider } from "@/components/live/live-events";
import { AppShell } from "@/components/shell/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { recognitions } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import { SessionProvider, useSession } from "@/lib/session";
import { useQuery } from "@tanstack/react-query";

/** Shown while `/me` is in flight: the shell's shape, none of its content. */
function ShellSkeleton() {
  return (
    <div className="relative z-10 min-h-dvh md:pl-[76px]">
      <div className="fixed inset-y-0 left-0 hidden w-[76px] border-r border-line md:block" />
      <div className="h-14 border-b border-line" />
      <div className="knori-gutter mx-auto w-full max-w-3xl pt-10">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="mt-4 h-4 w-80" />
        <Skeleton className="mt-10 h-40 w-full rounded-lg" />
        <span className="sr-only">
          <Spinner label="Loading KnoRI" />
        </span>
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user } = useSession();

  const summary = useQuery({
    queryKey: keys.recognitionSummary,
    queryFn: recognitions.summary,
    staleTime: 30_000,
  });

  if (!user) return <ShellSkeleton />;

  return (
    <AppShell
      user={{ display_name: user.preferred_name ?? user.display_name, email: user.email }}
      unreadRecognitions={summary.data?.unread ?? 0}
    >
      {children}
    </AppShell>
  );
}

/**
 * Everything under `/app` needs the same three things: a signed-in user, a live
 * event connection, and the nav. Doing it in one client component keeps the
 * route segment layouts free of hooks.
 */
export function AppGate({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider fallback={<ShellSkeleton />}>
      <LiveEventsProvider>
        <Shell>{children}</Shell>
      </LiveEventsProvider>
    </SessionProvider>
  );
}
