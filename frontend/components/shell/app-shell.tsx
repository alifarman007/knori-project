"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { ThemeToggle } from "@/components/theme";
import { isActive, NAV_ITEMS } from "@/components/shell/nav-items";
import { UserMenu } from "@/components/shell/user-menu";
import { CountBadge } from "@/components/ui/badge";
import { Wordmark } from "@/components/wordmark";
import { cn } from "@/lib/utils";

export interface AppShellProps {
  children: React.ReactNode;
  user: { display_name: string; email: string };
  /** Unread Recognitions, shown on the nav item and nowhere else. */
  unreadRecognitions?: number;
}

/**
 * Left rail from `md` up, bottom tab bar below it.
 *
 * There are four places and no more, because a product that keeps score of you
 * should be easy to hold in your head. The unread count appears once, on
 * Recognitions — nothing else in KnoRI nags.
 */
export function AppShell({ children, user, unreadRecognitions = 0 }: AppShellProps) {
  const pathname = usePathname();

  return (
    <div className="relative z-10 min-h-dvh md:pl-[76px]">
      {/* ------------------------------------------------------ left rail */}
      <nav
        aria-label="Sections"
        className="fixed inset-y-0 left-0 z-30 hidden w-[76px] flex-col items-center gap-1 border-r border-line bg-paper/90 py-4 backdrop-blur-md md:flex"
      >
        <Wordmark size="sm" className="mb-4" />
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const count = item.badge === "recognitions" ? unreadRecognitions : 0;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex w-[60px] flex-col items-center gap-1 rounded-md px-1 py-2.5",
                "transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                active ? "bg-sunken text-ink" : "text-ink-muted hover:bg-sunken/70 hover:text-ink",
              )}
            >
              {active ? (
                <span
                  aria-hidden="true"
                  className="absolute -left-[13px] top-1/2 h-6 w-[2px] -translate-y-1/2 rounded-full bg-accent"
                />
              ) : null}
              <span className="relative">
                <item.icon className="size-[22px]" />
                {count > 0 ? (
                  <CountBadge
                    count={count}
                    label={`${count} unread Recognitions`}
                    className="absolute -right-2.5 -top-1.5"
                  />
                ) : null}
              </span>
              <span className="text-[10px] font-medium leading-tight">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* --------------------------------------------------------- header */}
      <header className="sticky top-0 z-20 border-b border-line bg-paper/85 backdrop-blur-md">
        <div className="knori-gutter flex h-14 items-center gap-3">
          <Wordmark size="sm" className="md:hidden" />
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <UserMenu name={user.display_name} email={user.email} />
          </div>
        </div>
      </header>

      <main id="main" className="pb-24 md:pb-10">
        {children}
      </main>

      {/* ------------------------------------------------------- tab bar */}
      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper/95 backdrop-blur-md md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <ul className="flex">
          {NAV_ITEMS.map((item) => {
            const active = isActive(pathname, item.href);
            const count = item.badge === "recognitions" ? unreadRecognitions : 0;
            return (
              <li key={item.href} className="flex-1">
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex flex-col items-center gap-1 py-2.5",
                    "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus",
                    active ? "text-ink" : "text-ink-muted",
                  )}
                >
                  <span className="relative">
                    <item.icon className="size-[22px]" />
                    {count > 0 ? (
                      <CountBadge
                        count={count}
                        label={`${count} unread Recognitions`}
                        className="absolute -right-2.5 -top-1.5"
                      />
                    ) : null}
                  </span>
                  <span className="text-[10px] font-medium leading-tight">{item.label}</span>
                  {active ? (
                    <span aria-hidden="true" className="h-[2px] w-6 rounded-full bg-accent" />
                  ) : (
                    <span aria-hidden="true" className="h-[2px] w-6" />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
