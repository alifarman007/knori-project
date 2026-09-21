"use client";

import * as React from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface FieldContextValue {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
}

const FieldContext = React.createContext<FieldContextValue | null>(null);

/** Inputs read their id, aria-describedby and invalid state from here. */
export function useFieldContext(): FieldContextValue | null {
  return React.useContext(FieldContext);
}

export interface FieldProps {
  label: React.ReactNode;
  children: React.ReactNode;
  /** Shown under the control until an error replaces it. */
  hint?: React.ReactNode;
  error?: string | undefined;
  optional?: boolean;
  className?: string;
  /** Right-aligned extra, e.g. a "Forgot?" link next to a password label. */
  action?: React.ReactNode;
}

export function Field({ label, children, hint, error, optional, className, action }: FieldProps) {
  const reactId = React.useId();
  const id = `f${reactId.replace(/:/g, "")}`;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;

  const value = React.useMemo<FieldContextValue>(
    () => ({ id, describedBy, invalid: Boolean(error) }),
    [id, describedBy, error],
  );

  return (
    <FieldContext.Provider value={value}>
      <div className={cn("flex flex-col gap-1.5", className)}>
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor={id} optional={optional}>
            {label}
          </Label>
          {action}
        </div>
        {children}
        {error ? (
          <p id={errorId} className="flex items-start gap-1.5 text-sm text-danger">
            <svg viewBox="0 0 16 16" aria-hidden="true" className="mt-[3px] size-3.5 shrink-0">
              <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 4.5v4.2M8 11.2v.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span>{error}</span>
          </p>
        ) : hint ? (
          <p id={hintId} className="text-sm text-ink-muted">
            {hint}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  );
}
