import Link from "next/link";

import { ThemeToggle } from "@/components/theme";
import { Wordmark } from "@/components/wordmark";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative z-10 min-h-dvh lg:grid lg:grid-cols-2">
      <div className="flex min-h-dvh flex-col">
        <header className="knori-gutter flex h-16 items-center justify-between">
          <Wordmark />
          <ThemeToggle />
        </header>

        <main id="main" className="knori-gutter flex flex-1 items-center py-10">
          <div className="mx-auto w-full max-w-sm">{children}</div>
        </main>

        <footer className="knori-gutter flex h-16 items-center gap-4 text-sm text-ink-muted">
          <Link
            href="/legal/privacy"
            className="underline-offset-4 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            Privacy
          </Link>
          <Link
            href="/legal/terms"
            className="underline-offset-4 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            Terms
          </Link>
          <span className="ml-auto">draft-0</span>
        </footer>
      </div>

      {/* The quiet half. Hidden on phones, where it would only be scrolling. */}
      <aside className="relative hidden overflow-hidden border-l border-line bg-sunken/60 lg:block">
        <div
          aria-hidden="true"
          className="knori-ruled pointer-events-none absolute inset-0 opacity-50 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]"
        />
        <div className="relative flex h-full items-center px-14">
          <figure className="max-w-md">
            <p className="knori-eyebrow">What a Recognition sounds like</p>
            <blockquote className="mt-6 font-serif text-2xl leading-snug text-ink">
              &ldquo;It looks like writing is how you reach a decision rather than how you record
              one.&rdquo;
            </blockquote>
            <figcaption className="mt-6 border-l-2 border-accent-line pl-4 text-base text-ink-secondary">
              Built from three things you said, across two days — each one shown to you in your own
              words, with the day you said it.
            </figcaption>
          </figure>
        </div>
      </aside>
    </div>
  );
}
