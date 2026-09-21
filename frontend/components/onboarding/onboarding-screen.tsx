"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";

import { NotedSummary } from "@/components/onboarding/noted-summary";
import { DEFAULT_QUESTIONS } from "@/components/onboarding/questions";
import { StepAbout } from "@/components/onboarding/step-about";
import { StepConsent } from "@/components/onboarding/step-consent";
import { StepQuestions } from "@/components/onboarding/step-questions";
import { Skeleton } from "@/components/ui/skeleton";
import { onboarding } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import { useSession } from "@/lib/session";
import type { OnboardingNote } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

type Phase = 1 | 2 | 3 | 4;

const STEP_LABELS = ["About you", "What this is", "Three questions"] as const;

function Progress({ phase }: { phase: Phase }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Onboarding progress">
      {STEP_LABELS.map((label, index) => {
        const step = index + 1;
        const done = phase > step;
        const current = phase === step;
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-full px-2.5 py-1 text-xs transition-colors",
                current ? "bg-accent-soft text-ink" : done ? "text-ink-muted" : "text-ink-muted/70",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "size-1.5 rounded-full",
                  done ? "bg-accent" : current ? "bg-accent" : "bg-line-strong",
                )}
              />
              <span className="hidden sm:inline">{label}</span>
              <span className="sm:hidden">{step}</span>
            </span>
            {index < STEP_LABELS.length - 1 ? (
              <span aria-hidden="true" className="h-px w-4 bg-line" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The whole of `/onboarding`.
 *
 * The server's state decides where to resume — refreshing halfway through must
 * not put someone back at question one — and the local phase only moves
 * forward from there.
 */
export function OnboardingScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reportError = useErrorToast();
  const { user } = useSession();

  const [phase, setPhase] = React.useState<Phase | null>(null);
  const [noted, setNoted] = React.useState<OnboardingNote[]>([]);
  const [finishing, setFinishing] = React.useState(false);

  const state = useQuery({
    queryKey: keys.onboarding,
    queryFn: onboarding.state,
    retry: false,
  });

  // Resume where the server says they are, once.
  const resumed = React.useRef(false);
  React.useEffect(() => {
    if (resumed.current || state.isPending) return;
    resumed.current = true;
    const server = state.data;
    if (server?.complete) {
      setNoted(server.noted ?? []);
      setPhase(4);
      return;
    }
    const step = server?.step ?? 1;
    setPhase(step >= 3 ? 3 : step === 2 ? 2 : 1);
    if (server?.noted?.length) setNoted(server.noted);
  }, [state.isPending, state.data]);

  const questions =
    state.data?.questions && state.data.questions.length > 0
      ? state.data.questions
      : DEFAULT_QUESTIONS;
  const answered = state.data?.answers?.length ?? 0;

  async function finish() {
    setFinishing(true);
    try {
      const result = await onboarding.complete();
      if (result?.noted?.length) setNoted(result.noted);
      await queryClient.invalidateQueries({ queryKey: keys.session });
      router.replace("/app/chat");
    } catch (error) {
      reportError(error, "That could not be finished");
      setFinishing(false);
    }
  }

  if (phase === null) {
    return (
      <div aria-busy="true" className="flex flex-col gap-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80" />
        <Skeleton className="mt-6 h-48 w-full rounded-lg" />
      </div>
    );
  }

  return (
    <div>
      {phase < 4 ? <Progress phase={phase} /> : null}

      <div className={cn(phase < 4 && "mt-8")}>
        {phase === 1 ? (
          <StepAbout onDone={() => setPhase(2)} />
        ) : phase === 2 ? (
          <StepConsent onDone={() => setPhase(3)} onBack={() => setPhase(1)} />
        ) : phase === 3 ? (
          <StepQuestions
            questions={questions}
            answered={answered}
            onFinished={(captured) => {
              setNoted(captured);
              setPhase(4);
            }}
          />
        ) : (
          <NotedSummary noted={noted} starting={finishing} onStart={() => void finish()} />
        )}
      </div>

      {user && phase === 1 ? (
        <p className="mt-10 border-t border-line pt-5 text-sm text-ink-muted">
          Signed in as {user.email}.
        </p>
      ) : null}
    </div>
  );
}
