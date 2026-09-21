"use client";

import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { auth, me as meApi } from "@/lib/endpoints";
import { useForm } from "@/lib/use-form";
import { useErrorToast } from "@/lib/use-error-toast";
import {
  validateCurrentPassword,
  validateMatch,
  validatePassword,
} from "@/lib/validation";

const INITIAL = { current_password: "", new_password: "", confirm: "" };

export function PasswordForm() {
  const { toast } = useToast();
  const reportError = useErrorToast();
  const [signingOut, setSigningOut] = React.useState(false);

  const form = useForm({
    initial: INITIAL,
    validate: React.useCallback(
      (values: typeof INITIAL) => ({
        current_password: validateCurrentPassword(values.current_password),
        new_password: validatePassword(values.new_password),
        confirm:
          validatePassword(values.confirm) ?? validateMatch(values.confirm, values.new_password),
      }),
      [],
    ),
    onSubmit: React.useCallback(
      async (values: typeof INITIAL) => {
        await meApi.changePassword({
          current_password: values.current_password,
          new_password: values.new_password,
        });
        toast({
          title: "Password changed",
          description: "Other sessions were signed out.",
          tone: "positive",
        });
      },
      [toast],
    ),
  });

  async function logoutEverywhere() {
    setSigningOut(true);
    try {
      await auth.logoutAll();
      window.location.href = "/login";
    } catch (error) {
      reportError(error, "You could not be signed out");
      setSigningOut(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-5">
        {form.formError ? (
          <Alert tone="danger" title="That did not work">
            {form.formError}
          </Alert>
        ) : null}

        <Field label="Current password" error={form.errors.current_password}>
          <Input
            name="current_password"
            type="password"
            autoComplete="current-password"
            value={form.values.current_password}
            onChange={(event) => form.setValue("current_password", event.target.value)}
            onBlur={() => form.blur("current_password")}
          />
        </Field>

        <Field
          label="New password"
          error={form.errors.new_password}
          hint="At least 10 characters. A short sentence beats a clever string."
        >
          <Input
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={form.values.new_password}
            onChange={(event) => form.setValue("new_password", event.target.value)}
            onBlur={() => form.blur("new_password")}
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

        <div>
          <Button type="submit" loading={form.submitting} loadingText="Changing…">
            Change password
          </Button>
        </div>
      </form>

      <div className="border-t border-line pt-6">
        <p className="text-base text-ink-secondary">
          Signed in somewhere you no longer trust? This ends every session, including this one.
        </p>
        <Button
          variant="secondary"
          className="mt-3"
          loading={signingOut}
          onClick={() => void logoutEverywhere()}
        >
          Sign out everywhere
        </Button>
      </div>
    </div>
  );
}
