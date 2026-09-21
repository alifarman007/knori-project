"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { IconMenu } from "@/components/icons";
import { ThemeToggle } from "@/components/theme";
import { buttonStyles } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Wordmark } from "@/components/wordmark";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/pricing", label: "Pricing" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = React.useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="knori-gutter mx-auto flex h-16 w-full max-w-6xl items-center gap-4">
        <Wordmark />

        <nav aria-label="Main" className="ml-6 hidden items-center gap-1 md:flex">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={pathname === link.href ? "page" : undefined}
              className={cn(
                "rounded-sm px-3 py-2 text-base transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                pathname === link.href ? "text-ink" : "text-ink-muted hover:text-ink",
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <Link href="/login" className={cn(buttonStyles("ghost", "sm"), "hidden sm:inline-flex")}>
            Sign in
          </Link>
          <Link href="/signup" className={cn(buttonStyles("primary", "sm"), "hidden sm:inline-flex")}>
            Request an invite
          </Link>
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            className="grid size-9 place-items-center rounded-md text-ink-muted transition-colors hover:bg-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus sm:hidden"
          >
            <IconMenu />
          </button>
        </div>
      </div>

      <Sheet open={menuOpen} onClose={() => setMenuOpen(false)} title="Menu">
        <nav aria-label="Mobile" className="flex flex-col gap-1 pb-4">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setMenuOpen(false)}
              className="rounded-md px-3 py-3 text-md text-ink transition-colors hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              {link.label}
            </Link>
          ))}
          <div className="mt-4 flex flex-col gap-2">
            <Link
              href="/signup"
              onClick={() => setMenuOpen(false)}
              className={buttonStyles("primary", "md", "w-full")}
            >
              Request an invite
            </Link>
            <Link
              href="/login"
              onClick={() => setMenuOpen(false)}
              className={buttonStyles("secondary", "md", "w-full")}
            >
              Sign in
            </Link>
          </div>
        </nav>
      </Sheet>
    </header>
  );
}
