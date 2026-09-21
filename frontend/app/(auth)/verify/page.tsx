"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { AuthHeading } from "@/components/auth/auth-heading";
import { IconCheck } from "@/components/icons";
import { Alert } from "@/components/ui/alert";
import { Button, buttonStyles } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/endpoints";
import { validateEmail } from "@/lib/validation";

type Status = "checking" | "verified" | "expired" | "missing";

function VerifyState() {
  const params = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = React.useState<Status>(token ? "checking" : "missing");
  const [email, setEmail] = React.useState(params.get("email") ?? "");
  const [emailError, setEmailError] = React.useState<string | undefined>(undefined);
  const [resending, setResending] = React.useState(false);
  const [resent, setResent] = React.useState(false);

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void auth
      .verifyEmail(token)
      .then(() => {
        if (!cancelled) setStatus("verified");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // A spent or stale token is the common case. A 5xx gets the same screen,
        // because the only thing a person can do about either is ask for a new one.
        const rejected = error instanceof ApiError && error.status > 0 && error.status < 500;
        setStatus(rejected ? "expired" : "missing");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function resend() {
    const problem = validateEmail(email);
    setEmailError(problem);
    if (problem) return;

    setResending(true);
    try {
      await auth.resendVerification(email.trim());
    } catch {
      // The API answers the same whether or not the address exists, and so do we.
    } finally {
      setResending(false);
      setResent(true);
    }
  }

  if (status === "checking") {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <Spinner label={null} className="text-accent" />
        <p className="mt-4 text-base text-ink-muted">Checking your link…</p>
      </div>
    );
  }

  if (status === "verified") {
    return (
      <div>
        <span className="mb-6 grid size-12 place-items-center rounded-full bg-positive-soft text-positive">
          <IconCheck />
        </span>
        <AuthHeading
          title="Email confirmed"
          description="Your account is ready. KnoRI will ask you three short questions and then you can start talking."
        />
        <Link href="/onboarding" className={buttonStyles("primary", "lg", "w-full")}>
          Start
        </Link>
      </div>
    );
  }

  return (
    <div>
      <AuthHeading
        title={status === "missing" ? "Confirm your email" : "That link has expired"}
        description={
          status === "missing"
            ? "Open the link in the email we sent you. If it has gone missing, send yourself another."
            : "Verification links last 24 hours. Send yourself a new one and use the newest email."
        }
      />

      {resent ? (
        <Alert tone="positive" title="Sent" live>
          If that address has an account waiting to be confirmed, a new link is on its way. Check
          spam if it does not appear within a minute.
        </Alert>
      ) : (
        <div className="flex flex-col gap-4">
          <Field label="Your email" error={emailError}>
            <Input
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                if (emailError) setEmailError(undefined);
              }}
            />
          </Field>
          <Button fullWidth size="lg" loading={resending} onClick={() => void resend()}>
            Send a new link
          </Button>
        </div>
      )}

      <p className="mt-8 border-t border-line pt-6 text-sm text-ink-muted">
        Wrong address?{" "}
        <Link href="/signup" className="text-ink underline underline-offset-4">
          Start again
        </Link>
      </p>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <VerifyState />
    </React.Suspense>
  );
}
