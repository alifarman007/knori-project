import Link from "next/link";

import { Wordmark } from "@/components/wordmark";

const GROUPS = [
  {
    title: "Product",
    links: [
      { href: "/how-it-works", label: "How it works" },
      { href: "/pricing", label: "Pricing" },
      { href: "/signup", label: "Request an invite" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/legal/privacy", label: "Privacy" },
      { href: "/legal/terms", label: "Terms" },
    ],
  },
] as const;

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-line bg-sunken/60">
      <div className="knori-gutter mx-auto w-full max-w-6xl py-12">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <Wordmark />
            <p className="mt-4 max-w-sm text-base text-ink-muted">
              A chat that remembers what you tell it, and only says what it has noticed once it can
              show you the words behind it.
            </p>
          </div>

          {GROUPS.map((group) => (
            <div key={group.title}>
              <h2 className="knori-eyebrow font-sans">{group.title}</h2>
              <ul className="mt-4 flex flex-col gap-2.5">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-base text-ink-secondary underline-offset-4 transition-colors hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-2 border-t border-line pt-6 text-sm text-ink-muted sm:flex-row sm:items-center sm:justify-between">
          <p>KnoRI runs on the Recognition Operating System, built for Sway.</p>
          <p>Phase 1 · invite only · legal texts are draft-0</p>
        </div>
      </div>
    </footer>
  );
}
