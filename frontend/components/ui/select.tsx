"use client";

import * as React from "react";

import { useFieldContext } from "@/components/ui/field";
import { controlStyles } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  children: React.ReactNode;
}

/**
 * A native select. It inherits the input styling and the field wiring, and the
 * platform gets to draw the list — which on a phone is a far better control
 * than anything we would build.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, id, children, "aria-describedby": describedBy, "aria-invalid": invalid, ...props },
  ref,
) {
  const field = useFieldContext();

  return (
    <div className="relative">
      <select
        ref={ref}
        id={id ?? field?.id}
        aria-describedby={describedBy ?? field?.describedBy}
        aria-invalid={invalid ?? (field?.invalid ? true : undefined)}
        className={cn(controlStyles, "appearance-none pr-9", className)}
        {...props}
      >
        {children}
      </select>
      <svg
        viewBox="0 0 16 16"
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted"
      >
        <path d="m4.5 6.5 3.5 3.5 3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </div>
  );
});
