"use client";

import Link from "next/link";
import * as React from "react";

import { IconChevronDown } from "@/components/icons";
import { Avatar } from "@/components/ui/avatar";
import { auth } from "@/lib/endpoints";
import { cn } from "@/lib/utils";

export interface UserMenuProps {
  name: string;
  email: string;
}

const ITEMS = [
  { href: "/app/settings", label: "Settings" },
  { href: "/app/memory", label: "What KnoRI knows" },
  { href: "/how-it-works", label: "How it works" },
] as const;

export function UserMenu({ name, email }: UserMenuProps) {
  const [open, setOpen] = React.useState(false);
  const wrapperRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={cn(
          "flex items-center gap-2 rounded-md py-1 pl-1 pr-2 transition-colors hover:bg-sunken",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        <Avatar name={name} size="sm" />
        <span className="hidden text-sm text-ink-secondary sm:inline">{name}</span>
        <IconChevronDown className="size-4 text-ink-muted" />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+6px)] z-40 w-60 rounded-md border border-line bg-raised p-1.5 shadow-float animate-fade"
        >
          <div className="border-b border-line px-2.5 pb-2.5 pt-1.5">
            <p className="truncate text-sm font-medium text-ink">{name}</p>
            <p className="truncate text-xs text-ink-muted">{email}</p>
          </div>
          {ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block rounded-sm px-2.5 py-2 text-base text-ink-secondary transition-colors hover:bg-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus"
            >
              {item.label}
            </Link>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              // A full navigation clears every cached query with the session.
              void auth.logout().finally(() => window.location.assign("/login"));
            }}
            className="mt-1 block w-full rounded-sm border-t border-line px-2.5 pb-2 pt-2.5 text-left text-base text-ink-secondary transition-colors hover:bg-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus"
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
