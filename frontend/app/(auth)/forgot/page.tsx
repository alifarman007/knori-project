"use client";

import Link from "next/link";
import * as React from "react";

import { AuthHeading } from "@/components/auth/auth-heading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { auth } from "@/lib/endpoints";
import { useForm } from "@/lib/use-form";
import { validateEmail } from "@/lib/validation";

const INITIAL = { email: "" };

export default function ForgotPasswordPage() {
  const form = useForm({
    initial: INITIAL,
    validate: React.useCallback(
      (values: typeof INITIAL) => ({ email: validateEmail(values.email) }),
      [],
    ),
    onSubmit: (values: typeof INITIAL) => auth.forgotPassword(values.email.trim()),
  });

  if (form.submitted) {
    return (
      <div>
        <AuthHeading
          title="Check your email"
          description="If that address has an account, a reset link is on its way. The link works once and expires in an hour."
        />
        <Alert tone="info" title="Still nothing after a few minutes?">
          Look in spam, then try again — and check the address for a typo.
        </Alert>
        <div className="mt-6 flex flex-col gap-3">
          <Button variant="secondary" fullWidth onClick={form.reset}>
            Try another address
          </Button>
          <Link
            href="/login"
            className="text-center text-sm text-ink-muted underline-offset-4 hover:text-ink hover:underline"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <AuthHeading
        title="Reset your password"
        description="Give us the address you signed up with and we will send a link."
      />

      <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-4">
        {form.formError ? (
          <Alert tone="danger" title="That did not work">
            {form.formError}
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

        <Button type="submit" fullWidth size="lg" loading={form.submitting} className="mt-2">
          Send the link
        </Button>
      </form>

      <p className="mt-8 border-t border-line pt-6 text-sm text-ink-muted">
        Remembered it?{" "}
        <Link href="/login" className="text-ink underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}
