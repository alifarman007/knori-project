"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
}

/**
 * A labelled on/off control. The label is part of the component rather than a
 * sibling, so the hit area and the accessible name can never drift apart.
 */
export function Switch({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
  className,
  id,
}: SwitchProps) {
  const reactId = React.useId();
  const switchId = id ?? `s${reactId.replace(/:/g, "")}`;
  const descriptionId = description ? `${switchId}-desc` : undefined;

  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <label htmlFor={switchId} className="block text-base font-medium text-ink">
          {label}
        </label>
        {description ? (
          <p id={descriptionId} className="mt-0.5 text-sm text-ink-muted">
            {description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        id={switchId}
        aria-checked={checked}
        aria-describedby={descriptionId}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          "relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-200",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
          checked ? "border-accent bg-accent" : "border-line-strong bg-sunken",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "size-[18px] rounded-full bg-surface shadow-soft transition-transform duration-200",
            checked ? "translate-x-[22px]" : "translate-x-[3px]",
          )}
        />
      </button>
    </div>
  );
}
