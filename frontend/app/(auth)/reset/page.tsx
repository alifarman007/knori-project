"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { AuthHeading } from "@/components/auth/auth-heading";
import { Alert } from "@/components/ui/alert";
import { Button, buttonStyles } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { auth } from "@/lib/endpoints";
import { useForm } from "@/lib/use-form";
import { validateMatch, validatePassword } from "@/lib/validation";

const INITIAL = { password: "", confirm: "" };

function ResetForm() {
  const token = useSearchParams().get("token");

  const form = useForm({
    initial: INITIAL,
    validate: React.useCallback(
      (values: typeof INITIAL) => ({
        password: validatePassword(values.password),
        confirm: validatePassword(values.confirm) ?? validateMatch(values.confirm, values.password),
      }),
      [],
    ),
    onSubmit: (values: typeof INITIAL) => auth.resetPassword(token ?? "", values.password),
  });

  if (!token) {
    return (
      <div>
        <AuthHeading title="That link is incomplete" />
        <Alert tone="danger" title="No reset token in the address">
          Reset links work once and expire after an hour. Ask for a new one and use the newest email.
        </Alert>
        <Link href="/forgot" className={buttonStyles("primary", "lg", "mt-6 w-full")}>
          Send a new link
        </Link>
      </div>
    );
  }

  if (form.submitted) {
    return (
      <div>
        <AuthHeading
          title="Password changed"
          description="Every other session has been signed out, so anyone using your old password is gone."
        />
        <Link href="/login" className={buttonStyles("primary", "lg", "w-full")}>
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <div>
      <AuthHeading title="Choose a new password" description="At least 10 characters." />

      <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-4">
        {form.formError ? (
          <Alert tone="danger" title="That did not work">
            {form.formError}
          </Alert>
        ) : null}

        <Field
          label="New password"
          error={form.errors.password}
          hint="A short sentence you will remember beats a clever string you will not."
        >
          <Input
            name="password"
            type="password"
            autoComplete="new-password"
            autoFocus
            value={form.values.password}
            onChange={(event) => form.setValue("password", event.target.value)}
            onBlur={() => form.blur("password")}
          />
        </Field>

        <Field label="Type it again" error={form.errors.confirm}>
          <Input
            name="confirm"
            type="password"
            autoComplete="new-password"
            value={form.values.confirm}
            onChange={(event) => form.setValue("confirm", event.target.value)}
            onBlur={() => form.blur("confirm")}
          />
        </Field>

        <Button type="submit" fullWidth size="lg" loading={form.submitting} className="mt-2">
          Change password
        </Button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ResetForm />
    </React.Suspense>
  );
}
