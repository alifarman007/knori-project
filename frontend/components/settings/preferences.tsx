"use client";

import { useMutation } from "@tanstack/react-query";
import * as React from "react";

import { Field } from "@/components/ui/field";
import { Segmented } from "@/components/ui/chip";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { me as meApi } from "@/lib/endpoints";
import { useSession } from "@/lib/session";
import type { ChatStyle, UserSettings } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";

const PER_DAY = [0, 1, 2, 3, 4, 5] as const;

function perDayLabel(value: number): string {
  if (value === 0) return "None — hold them all";
  if (value === 1) return "At most one a day";
  return `At most ${value} a day`;
}

/**
 * Saving a settings switch.
 *
 * Each control saves on change and rolls back if the save fails, because a
 * settings page with a Save button invites people to leave without pressing it
 * and then wonder why nothing changed.
 */
function useSettingSaver() {
  const { settings, setSettings } = useSession();
  const reportError = useErrorToast();

  const save = useMutation({
    mutationFn: (patch: Partial<UserSettings>) => meApi.updateSettings(patch),
    onSuccess: (updated) => setSettings(updated),
    onError: (error, _patch, context) => {
      if (context) setSettings(context as UserSettings);
      reportError(error, "That setting did not save");
    },
    onMutate: (patch) => {
      const previous = settings;
      if (settings) setSettings({ ...settings, ...patch });
      return previous;
    },
  });

  return { settings, save };
}

/** What KnoRI is allowed to tell you, and how often. */
export function Preferences() {
  const { settings, save } = useSettingSaver();
  const { toast } = useToast();

  if (!settings) return null;

  return (
    <div className="flex flex-col gap-7">
      <Switch
        checked={settings.recognition_enabled}
        onCheckedChange={(checked) => {
          save.mutate({ recognition_enabled: checked });
          if (!checked) {
            toast({
              title: "Recognitions paused",
              description: "KnoRI keeps listening, but it will not show you anything it notices.",
            });
          }
        }}
        label="Show me Recognitions"
        description="With this off, KnoRI still remembers what you say — it simply stops telling you what it noticed."
      />

      <Field
        label="How many at most"
        hint="Two is the default. KnoRI rarely has more than that worth saying."
      >
        <Select
          value={String(settings.max_recognitions_per_day)}
          disabled={!settings.recognition_enabled}
          onChange={(event) =>
            save.mutate({ max_recognitions_per_day: Number(event.target.value) })
          }
        >
          {PER_DAY.map((value) => (
            <option key={value} value={value}>
              {perDayLabel(value)}
            </option>
          ))}
        </Select>
      </Field>

      <div>
        <p className="text-base font-medium text-ink">How KnoRI talks</p>
        <p className="mt-0.5 mb-2.5 text-sm text-ink-muted">
          Warm takes its time. Direct says the thing and stops.
        </p>
        <Segmented<ChatStyle>
          aria-label="How KnoRI talks"
          value={settings.chat_style}
          onChange={(value) => save.mutate({ chat_style: value })}
          options={[
            { value: "warm", label: "Warm" },
            { value: "direct", label: "Direct" },
          ]}
        />
      </div>
    </div>
  );
}

/** Memory is its own decision: it keeps working with Recognitions switched off. */
export function MemoryPreference() {
  const { settings, save } = useSettingSaver();
  const { toast } = useToast();

  if (!settings) return null;

  return (
    <div>
      <Switch
        checked={settings.memory_enabled}
        onCheckedChange={(checked) => {
          save.mutate({ memory_enabled: checked });
          if (!checked) {
            toast({
              title: "Memory paused",
              description:
                "Nothing new will be kept. What is already remembered stays until you retract it.",
            });
          }
        }}
        label="Remember what I say"
        description="With this off, nothing is extracted from your conversations and no new Recognition can be built."
      />
      <p className="mt-4 text-sm leading-relaxed text-ink-muted">
        Switching this off does not delete anything. What KnoRI already remembers stays on your
        memory page until you retract it.
      </p>
    </div>
  );
}
