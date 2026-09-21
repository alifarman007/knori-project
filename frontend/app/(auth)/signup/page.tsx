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
import {
  passwordStrength,
  validateDisplayName,
  validateEmail,
  validateInviteCode,
  validatePassword,
} from "@/lib/validation";
import { cn } from "@/lib/utils";

const INITIAL = { display_name: "", email: "", password: "", invite_code: "" };

export default function SignupPage() {
  const form = useForm({
    initial: INITIAL,
    validate: React.useCallback(
      (values: typeof INITIAL) => ({
        display_name: validateDisplayName(values.display_name),
        email: validateEmail(values.email),
        password: validatePassword(values.password),
        invite_code: validateInviteCode(values.invite_code, true),
      }),
      [],
    ),
    onSubmit: (values: typeof INITIAL) =>
      auth.register({
        email: values.email.trim(),
        password: values.password,
        display_name: values.display_name.trim(),
        ...(values.invite_code.trim() ? { invite_code: values.invite_code.trim() } : {}),
      }),
  });

  const strength = passwordStrength(form.values.password);

  if (form.submitted) {
    return (
      <div>
        <AuthHeading
          title="Check your email"
          description={
            <>
              We sent a link to <span className="text-ink">{form.values.email}</span>. Open it and
              KnoRI is ready.
            </>
          }
        />
        <Alert tone="info" title="Nothing arrived?">
          Give it a minute, then look in spam — verification mail often lands there the first time.
        </Alert>
        <div className="mt-6 flex flex-col gap-3">
          <Button variant="secondary" fullWidth onClick={form.reset}>
            Use a different address
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
        title="Create your account"
        description="KnoRI is invite only while it is in beta."
      />

      <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-4">
        {form.formError ? (
          <Alert tone="danger" title="That did not work">
            {form.formError}
            {form.requestId ? (
              <span className="mt-1 block font-mono text-2xs text-ink-muted">
                reference {form.requestId}
              </span>
            ) : null}
          </Alert>
        ) : null}

        <Field
          label="What should KnoRI call you?"
          error={form.errors.display_name}
          hint="A first name is plenty."
        >
          <Input
            name="display_name"
            autoComplete="name"
            value={form.values.display_name}
            onChange={(event) => form.setValue("display_name", event.target.value)}
            onBlur={() => form.blur("display_name")}
          />
        </Field>

        <Field label="Email" error={form.errors.email}>
          <Input
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            value={form.values.email}
            onChange={(event) => form.setValue("email", event.target.value)}
            onBlur={() => form.blur("email")}
          />
        </Field>

        <Field
          label="Password"
          error={form.errors.password}
          hint="At least 10 characters. A short sentence works better than symbols."
        >
          <Input
            name="password"
            type="password"
            autoComplete="new-password"
            value={form.values.password}
            onChange={(event) => form.setValue("password", event.target.value)}
            onBlur={() => form.blur("password")}
          />
        </Field>

        {form.values.password ? (
          <div className="-mt-2 flex items-center gap-3" aria-live="polite">
            <div className="flex h-1 flex-1 gap-1" aria-hidden="true">
              {[1, 2, 3, 4].map((step) => (
                <span
                  key={step}
                  className={cn(
                    "h-full flex-1 rounded-full transition-colors",
                    step <= strength.score ? "bg-accent" : "bg-line",
                  )}
                />
              ))}
            </div>
            <span className="w-14 text-right text-xs text-ink-muted">{strength.label}</span>
          </div>
        ) : null}

        <Field
          label="Invite code"
          error={form.errors.invite_code}
          hint="From your invitation email."
        >
          <Input
            name="invite_code"
            autoCapitalize="characters"
            autoComplete="off"
            className="font-mono tracking-widest"
            value={form.values.invite_code}
            onChange={(event) => form.setValue("invite_code", event.target.value.toUpperCase())}
            onBlur={() => form.blur("invite_code")}
          />
        </Field>

        <Button type="submit" fullWidth size="lg" loading={form.submitting} className="mt-2">
          Create account
        </Button>

        <p className="text-sm leading-relaxed text-ink-muted">
          Creating an account means you accept the{" "}
          <Link href="/legal/terms" className="text-accent underline underline-offset-4">
            terms
          </Link>{" "}
          and the{" "}
          <Link href="/legal/privacy" className="text-accent underline underline-offset-4">
            privacy note
          </Link>
          . Both are draft-0 during the beta, and you will be asked again when the final texts land.
        </p>
      </form>

      <p className="mt-8 border-t border-line pt-6 text-sm text-ink-muted">
        Already have an account?{" "}
        <Link href="/login" className="text-ink underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}
