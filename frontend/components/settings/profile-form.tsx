"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { me as meApi } from "@/lib/endpoints";
import { useSession } from "@/lib/session";
import { detectTimezone, timezoneLabel, timezoneOptions } from "@/lib/timezone";
import { useForm } from "@/lib/use-form";
import { useErrorToast } from "@/lib/use-error-toast";
import { validateDisplayName } from "@/lib/validation";

type Values = { display_name: string; preferred_name: string; timezone: string };

/**
 * Name, what to call you, and the timezone.
 *
 * The timezone is not cosmetic: rule R3 counts "two different calendar days" in
 * it, so the warning under the field is the literal truth about what changing it
 * does.
 */
export function ProfileForm() {
  const { user, setUser } = useSession();
  const { toast } = useToast();
  const reportError = useErrorToast();
  const [zones] = React.useState(() => timezoneOptions(user?.timezone));
  const detected = React.useMemo(detectTimezone, []);

  const form = useForm({
    initial: React.useMemo(
      () => ({
        display_name: user?.display_name ?? "",
        preferred_name: user?.preferred_name ?? "",
        timezone: user?.timezone ?? detected,
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
        toast({ title: "Saved", tone: "positive" });
      },
      [setUser, toast],
    ),
  });

  // The form helper reports field errors inline; anything else deserves a toast.
  React.useEffect(() => {
    if (form.formError) reportError(new Error(form.formError), "That did not save");
  }, [form.formError, reportError]);

  const zoneChanged = user ? form.values.timezone !== user.timezone : false;

  return (
    <form onSubmit={form.handleSubmit} noValidate className="flex flex-col gap-5">
      <Field label="Your name" error={form.errors.display_name}>
        <Input
          name="display_name"
          autoComplete="name"
          value={form.values.display_name}
          onChange={(event) => form.setValue("display_name", event.target.value)}
          onBlur={() => form.blur("display_name")}
        />
      </Field>

      <Field
        label="What KnoRI should call you"
        optional
        hint="Leave this empty and it uses your name."
      >
        <Input
          name="preferred_name"
          value={form.values.preferred_name}
          onChange={(event) => form.setValue("preferred_name", event.target.value)}
        />
      </Field>

      <Field
        label="Timezone"
        hint={
          zoneChanged
            ? "Changing this re-checks every Recognition: KnoRI counts days in your timezone."
            : `Your browser says ${timezoneLabel(detected)}.`
        }
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

      <div>
        <Button type="submit" loading={form.submitting} loadingText="Saving…">
          Save
        </Button>
      </div>
    </form>
  );
}
