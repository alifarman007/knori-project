import * as React from "react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A line drawing, not an emoji. */
  icon?: React.ReactNode;
  action?: React.ReactNode;
  /** Extra note under the action, e.g. why the wait is deliberate. */
  footnote?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  footnote,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center rounded-lg border border-dashed border-line-strong",
        "bg-sunken/60 px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? (
        <span aria-hidden="true" className="mb-4 text-ink-muted">
          {icon}
        </span>
      ) : null}
      <h3 className="font-serif text-lg text-ink">{title}</h3>
      {description ? (
        <p className="mt-2 max-w-sm text-base text-ink-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-6">{action}</div> : null}
      {footnote ? <p className="mt-4 max-w-sm text-sm text-ink-muted">{footnote}</p> : null}
    </div>
  );
}
