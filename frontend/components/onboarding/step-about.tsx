"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { me as meApi } from "@/lib/endpoints";
import { useSession } from "@/lib/session";
import { detectTimezone, timezoneLabel, timezoneOptions } from "@/lib/timezone";
import { useForm } from "@/lib/use-form";
import { validateDisplayName } from "@/lib/validation";

type Values = { display_name: string; preferred_name: string; timezone: string };

export interface StepAboutProps {
  onDone: () => void;
}

/**
 * Step one: who you are, and where you are.
 *
 * The timezone is detected and shown rather than asked for blind, because it
 * decides what counts as "a different day" — the rule that stops KnoRI turning
 * one long evening into a pattern.
 */
export function StepAbout({ onDone }: StepAboutProps) {
  const { user, setUser } = useSession();
  const detected = React.useMemo(detectTimezone, []);
  const [zones] = React.useState(() => timezoneOptions(user?.timezone));

  const form = useForm({
    initial: React.useMemo(
      () => ({
        display_name: user?.display_name ?? "",
        preferred_name: user?.preferred_name ?? "",
        timezone: user?.timezone && user.timezone !== "UTC" ? user.timezone : detected,
      }),
      [user, detected],
    ),
    validate: React.useCallback(
      (values: Values) => ({ display_name: validateDisplayName(values.display_name) }),
      [],
    ),
    onSubmit: React.useCallback(
      async (values: Values) => {
        const updated = await meApi.update({
          display_name: values.display_name.trim(),
          preferred_name: values.preferred_name.trim() || null,
          timezone: values.timezone,
        });
        setUser(updated);
        onDone();
      },
      [setUser, onDone],
    ),
  });

  return (
    <div>
      <h1 className="text-2xl">First, the basics</h1>
      <p className="mt-2 max-w-prose text-base text-ink-muted">
        Three short screens, then you can talk. Nothing here is locked in — all of it is on your
        settings page afterwards.
      </p>

      <form onSubmit={form.handleSubmit} noValidate className="mt-8 flex flex-col gap-5">
        <Field label="Your name" error={form.errors.display_name}>
          <Input
            name="display_name"
            autoComplete="name"
            autoFocus
            value={form.values.display_name}
            onChange={(event) => form.setValue("display_name", event.target.value)}
            onBlur={() => form.blur("display_name")}
          />
        </Field>

        <Field
          label="What should KnoRI call you?"
          optional
          hint="Leave it empty and it uses your name."
        >
          <Input
            name="preferred_name"
            value={form.values.preferred_name}
            onChange={(event) => form.setValue("preferred_name", event.target.value)}
          />
        </Field>

        <Field
          label="Where are you?"
          hint={`Detected as ${timezoneLabel(detected)}. KnoRI counts days in your timezone, which is how it knows two things were said on different days.`}
        >
          <Select
            name="timezone"
            value={form.values.timezone}
            onChange={(event) => form.setValue("timezone", event.target.value)}
          >
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {timezoneLabel(zone)}
              </option>
            ))}
          </Select>
        </Field>

        {form.formError ? (
          <p role="alert" className="text-sm text-danger">
            {form.formError}
          </p>
        ) : null}

        <div className="pt-2">
          <Button type="submit" size="lg" loading={form.submitting} loadingText="Saving…">
            Continue
          </Button>
        </div>
      </form>
    </div>
  );
}
