"use client";

import * as React from "react";

import { useFieldContext } from "@/components/ui/field";
import { cn } from "@/lib/utils";

export const controlStyles = cn(
  "w-full bg-surface text-ink rounded-md border border-line-strong",
  "px-3 py-2 text-base shadow-[inset_0_1px_2px_rgb(25_23_20/0.04)]",
  "transition-[border-color,box-shadow] duration-150",
  "hover:border-ink-muted/60",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus focus-visible:border-focus",
  "disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-muted",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:outline-danger",
);

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Decorative glyph on the left; it is hidden from assistive tech. */
  leading?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, leading, id, "aria-describedby": describedBy, "aria-invalid": invalid, ...props },
  ref,
) {
  const field = useFieldContext();
  const control = (
    <input
      ref={ref}
      id={id ?? field?.id}
      aria-describedby={describedBy ?? field?.describedBy}
      aria-invalid={invalid ?? (field?.invalid ? true : undefined)}
      className={cn(controlStyles, leading && "pl-9", className)}
      {...props}
    />
  );

  if (!leading) return control;

  return (
    <div className="relative">
      <span
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted"
      >
        {leading}
      </span>
      {control}
    </div>
  );
});
