import { ThemeToggle } from "@/components/theme";
import { Wordmark } from "@/components/wordmark";
import { SessionProvider } from "@/lib/session";

/**
 * Onboarding has no app shell on purpose: there is nowhere else to go yet, and
 * a nav rail with three empty sections would be the first thing a new person
 * saw. `requireOnboarding` is off here, or this page would redirect to itself.
 */
export default function OnboardingLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider requireOnboarding={false}>
      <div className="relative z-10 flex min-h-dvh flex-col">
        <header className="knori-gutter flex h-16 shrink-0 items-center justify-between">
          <Wordmark asLink={false} />
          <ThemeToggle />
        </header>

        <main id="main" className="knori-gutter flex-1 pb-16 pt-6">
          <div className="mx-auto w-full max-w-2xl">{children}</div>
        </main>
      </div>
    </SessionProvider>
  );
}
