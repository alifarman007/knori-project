"use client";

import Link from "next/link";
import * as React from "react";

import { PRIVACY_VERSION, TOS_VERSION } from "@/components/onboarding/questions";
import { Button } from "@/components/ui/button";
import { me as meApi } from "@/lib/endpoints";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

export interface StepConsentProps {
  onDone: () => void;
  onBack: () => void;
}

const POINTS: readonly { title: string; body: string }[] = [
  {
    title: "It keeps what you tell it",
    body: "Short statements taken from your messages, each stored with the exact words it came from and the day you said them. You can read, edit or retract every one.",
  },
  {
    title: "It will tell you what it noticed",
    body: "Only when the same thing shows up in what you said on at least two different days, twelve hours apart — and always with the quotes behind it.",
  },
  {
    title: "You can correct it",
    body: "A correction is not a complaint. What you write becomes something KnoRI has to reason with, and cards built on the old reading get withdrawn.",
  },
  {
    title: "Your words go to model providers",
    body: "Anthropic and OpenAI process your messages to produce replies. They are not used to train anybody's models, and nothing is sold or shared.",
  },
  {
    title: "You can leave with everything",
    body: "Export the lot as one file at any time, and delete the account with a day of grace to change your mind.",
  },
];

/**
 * Step two: consent, in the words the product actually behaves in.
 *
 * The acceptance is recorded against the version of each text, so a later
 * rewrite means asking again rather than assuming the old yes still counts.
 */
export function StepConsent({ onDone, onBack }: StepConsentProps) {
  const [agreed, setAgreed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const reportError = useErrorToast();
  const reactId = React.useId();
  const checkboxId = `ok${reactId.replace(/:/g, "")}`;

  async function accept() {
    if (!agreed) {
      setError("Tick the box to carry on.");
      return;
    }
    setBusy(true);
    try {
      await meApi.acceptLegal(TOS_VERSION, PRIVACY_VERSION);
      onDone();
    } catch (cause) {
      reportError(cause, "That could not be recorded");
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-2xl">What you are agreeing to</h1>
      <p className="mt-2 max-w-prose text-base text-ink-muted">
        In plain words, before the legal version. Both texts are drafts during the beta, and you
        will be asked again when the final ones land.
      </p>

      <ul className="mt-8 flex flex-col">
        {POINTS.map((point) => (
          <li key={point.title} className="border-b border-line py-4 first:pt-0 last:border-0">
            <p className="font-serif text-md text-ink">{point.title}</p>
            <p className="mt-1 max-w-prose text-base leading-relaxed text-ink-secondary">
              {point.body}
            </p>
          </li>
        ))}
      </ul>

      <label
        htmlFor={checkboxId}
        className={cn(
          "mt-7 flex cursor-pointer items-start gap-3 rounded-md border px-4 py-3.5 transition-colors",
          agreed ? "border-accent-line bg-accent-soft/50" : "border-line-strong bg-surface",
        )}
      >
        <input
          id={checkboxId}
          type="checkbox"
          checked={agreed}
          onChange={(event) => {
            setAgreed(event.target.checked);
            if (event.target.checked) setError(null);
          }}
          aria-describedby={error ? `${checkboxId}-error` : undefined}
          className="mt-0.5 size-4 shrink-0 accent-[var(--knori-accent)]"
        />
        <span className="text-base text-ink">
          I have read this, and I accept the{" "}
          <Link
            href="/legal/terms"
            target="_blank"
            className="text-accent underline underline-offset-4"
          >
            terms
          </Link>{" "}
          and the{" "}
          <Link
            href="/legal/privacy"
            target="_blank"
            className="text-accent underline underline-offset-4"
          >
            privacy note
          </Link>
          .
        </span>
      </label>

      {error ? (
        <p id={`${checkboxId}-error`} role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className="mt-7 flex flex-wrap items-center gap-3">
        <Button size="lg" loading={busy} onClick={() => void accept()}>
          I agree — carry on
        </Button>
        <Button variant="ghost" onClick={onBack} disabled={busy}>
          Back
        </Button>
      </div>
    </div>
  );
}
