"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { AuthHeading } from "@/components/auth/auth-heading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { auth } from "@/lib/endpoints";
import { useForm } from "@/lib/use-form";
import { validateCurrentPassword, validateEmail } from "@/lib/validation";

const INITIAL = { email: "", password: "" };

function LoginForm() {
  const next = useSearchParams().get("next");

  const form = useForm({
    initial: INITIAL,
    validate: React.useCallback(
      (values: typeof INITIAL) => ({
        email: validateEmail(values.email),
        password: validateCurrentPassword(values.password),
      }),
      [],
    ),
    onSubmit: async (values: typeof INITIAL) => {
      await auth.login(values.email.trim(), values.password);
      // A full navigation, so every cached query starts from the new session.
      window.location.assign(next && next.startsWith("/") ? next : "/app/chat");
    },
  });

  return (
    <div>
      <AuthHeading title="Welcome back" description="Pick up where you left off." />

      <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-4">
        {form.formError ? (
          <Alert tone="danger" title="Could not sign you in">
            {form.formError}
            {form.requestId ? (
              <span className="mt-1 block font-mono text-2xs text-ink-muted">
                reference {form.requestId}
              </span>
            ) : null}
          </Alert>
        ) : null}

        <Field label="Email" error={form.errors.email}>
          <Input
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            autoFocus
            value={form.values.email}
            onChange={(event) => form.setValue("email", event.target.value)}
            onBlur={() => form.blur("email")}
          />
        </Field>

        <Field
          label="Password"
          error={form.errors.password}
          action={
            <Link
              href="/forgot"
              className="text-sm text-ink-muted underline-offset-4 hover:text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              Forgot?
            </Link>
          }
        >
          <Input
            name="password"
            type="password"
            autoComplete="current-password"
            value={form.values.password}
            onChange={(event) => form.setValue("password", event.target.value)}
            onBlur={() => form.blur("password")}
          />
        </Field>

        <Button
          type="submit"
          fullWidth
          size="lg"
          loading={form.submitting}
          loadingText="Signing in…"
          className="mt-2"
        >
          Sign in
        </Button>
      </form>

      <p className="mt-8 border-t border-line pt-6 text-sm text-ink-muted">
        No account yet?{" "}
        <Link href="/signup" className="text-ink underline underline-offset-4">
          Request an invite
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-72 w-full" />}>
      <LoginForm />
    </React.Suspense>
  );
}
