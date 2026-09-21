"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Field } from "@/components/ui/field";
import { Sheet } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { REASON_CHIPS } from "@/lib/labels";
import type { ReasonCode } from "@/lib/types";

export const CORRECTION_MIN_LENGTH = 3;
export const CORRECTION_MAX_LENGTH = 600;

/** Exported so the rule can be tested without mounting the sheet. */
export function validateCorrection(text: string): string | undefined {
  const trimmed = text.trim();
  if (trimmed.length < CORRECTION_MIN_LENGTH) {
    return "Tell KnoRI what is actually true — a sentence is enough.";
  }
  if (trimmed.length > CORRECTION_MAX_LENGTH) {
    return `That is longer than ${CORRECTION_MAX_LENGTH} characters.`;
  }
  return undefined;
}

export interface CorrectionSheetProps {
  open: boolean;
  onClose: () => void;
  /** The claim being corrected, shown at the top so nobody argues from memory. */
  title: string;
  onSubmit: (input: { correction_text: string; reason_code?: ReasonCode }) => void;
  submitting?: boolean;
}

/**
 * "Not quite" — the most important control in the product.
 *
 * The free text is required and the category is not, because the text is what
 * becomes a `user_assertion` and actually changes future reasoning; the chip
 * only tells the engine how to weigh it. A correction that just hides the card
 * would be the failure mode this whole screen exists to avoid.
 */
export function CorrectionSheet({
  open,
  onClose,
  title,
  onSubmit,
  submitting = false,
}: CorrectionSheetProps) {
  const [reason, setReason] = React.useState<ReasonCode | null>(null);
  const [text, setText] = React.useState("");
  const [error, setError] = React.useState<string | undefined>(undefined);
  const textRef = React.useRef<HTMLTextAreaElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setReason(null);
    setText("");
    setError(undefined);
  }, [open]);

  function submit() {
    const problem = validateCorrection(text);
    setError(problem);
    if (problem) {
      textRef.current?.focus();
      return;
    }
    onSubmit({
      correction_text: text.trim(),
      ...(reason ? { reason_code: reason } : {}),
    });
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="What did KnoRI get wrong?"
      description="Your words are kept as they are and used from now on — this is not a way to hide the card."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={submit} loading={submitting} loadingText="Saving…">
            Save the correction
          </Button>
        </>
      }
    >
      <figure className="mb-5 border-l-2 border-accent-line pl-4">
        <figcaption className="knori-eyebrow">KnoRI said</figcaption>
        <p className="mt-1.5 font-serif text-md leading-relaxed text-ink">{title}</p>
      </figure>

      <fieldset className="mb-5">
        <legend className="mb-2.5 text-sm font-medium text-ink">
          What kind of wrong is it?{" "}
          <span className="font-normal text-ink-muted">optional</span>
        </legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {REASON_CHIPS.map((chip) => (
            <Chip
              key={chip.code}
              selected={reason === chip.code}
              hint={chip.hint}
              onClick={() => setReason((current) => (current === chip.code ? null : chip.code))}
            >
              {chip.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      <Field
        label="What is actually true?"
        error={error}
        hint={`In your own words. Up to ${CORRECTION_MAX_LENGTH} characters.`}
      >
        <Textarea
          ref={textRef}
          autoResize
          rows={4}
          maxRows={10}
          value={text}
          maxLength={CORRECTION_MAX_LENGTH + 100}
          onChange={(event) => {
            setText(event.target.value);
            if (error) setError(undefined);
          }}
          placeholder="It is not that I avoid deciding — I decide fast and then write it up."
        />
      </Field>

      <p className="mt-4 text-sm leading-relaxed text-ink-muted">
        KnoRI turns this into a claim it has to respect: cards built on the old reading are
        withdrawn, and the next reply is written with your version in front of it.
      </p>
    </Sheet>
  );
}
