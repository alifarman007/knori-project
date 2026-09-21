"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { MEMORY_KIND_HELP, MEMORY_KIND_LABEL, MEMORY_KIND_ORDER } from "@/lib/labels";
import type { MemoryItem, MemoryKind } from "@/lib/types";

export const STATEMENT_MAX_LENGTH = 300;

/** Exported for the test: the same rule the sheet enforces. */
export function validateStatement(value: string): string | undefined {
  const trimmed = value.trim();
  if (trimmed.length < 3) return "Write the thing you want KnoRI to remember.";
  if (trimmed.length > STATEMENT_MAX_LENGTH) {
    return `Keep it under ${STATEMENT_MAX_LENGTH} characters — one fact per line works best.`;
  }
  return undefined;
}

export interface MemoryEditorProps {
  open: boolean;
  onClose: () => void;
  /** `null` adds a new item; an item edits it. */
  item: MemoryItem | null;
  onSave: (input: { kind: MemoryKind; statement: string }) => void;
  saving?: boolean;
}

export function MemoryEditor({ open, onClose, item, onSave, saving = false }: MemoryEditorProps) {
  const [kind, setKind] = React.useState<MemoryKind>("fact");
  const [statement, setStatement] = React.useState("");
  const [error, setError] = React.useState<string | undefined>(undefined);

  React.useEffect(() => {
    if (!open) return;
    setKind(item?.kind ?? "fact");
    setStatement(item?.statement ?? "");
    setError(undefined);
  }, [open, item]);

  function save() {
    const problem = validateStatement(statement);
    setError(problem);
    if (problem) return;
    onSave({ kind, statement: statement.trim() });
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={item ? "Edit what KnoRI remembers" : "Tell KnoRI something"}
      description={
        item
          ? "Once you edit a memory, KnoRI stops overwriting it with its own version."
          : "Anything you add here is treated as yours, not as something KnoRI worked out."
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} loading={saving} loadingText="Saving…">
            {item ? "Save" : "Remember this"}
          </Button>
        </>
      }
    >
      <Field label="What kind of thing is it?" hint={MEMORY_KIND_HELP[kind]}>
        <Select value={kind} onChange={(event) => setKind(event.target.value as MemoryKind)}>
          {MEMORY_KIND_ORDER.map((value) => (
            <option key={value} value={value}>
              {MEMORY_KIND_LABEL[value]}
            </option>
          ))}
        </Select>
      </Field>

      <Field
        label="In one sentence"
        className="mt-5"
        error={error}
        hint={`Written as a plain statement. Up to ${STATEMENT_MAX_LENGTH} characters.`}
      >
        <Textarea
          autoResize
          rows={3}
          maxRows={8}
          value={statement}
          maxLength={STATEMENT_MAX_LENGTH + 50}
          onChange={(event) => {
            setStatement(event.target.value);
            if (error) setError(undefined);
          }}
          placeholder="I do my best thinking before ten in the morning."
        />
      </Field>

      {kind === "relationship" ? (
        <p className="mt-4 text-sm leading-relaxed text-ink-muted">
          Write this as something about you, not about them. KnoRI keeps your own words about the
          people in your life and never builds a picture of anybody else.
        </p>
      ) : null}
    </Sheet>
  );
}
