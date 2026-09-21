import * as React from "react";

import { cn } from "@/lib/utils";

export interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  /** Marks the field optional in words rather than marking the rest with *. */
  optional?: boolean;
}

export function Label({ className, children, optional, ...props }: LabelProps) {
  return (
    <label
      className={cn("flex items-baseline gap-2 text-sm font-medium text-ink", className)}
      {...props}
    >
      <span>{children}</span>
      {optional ? <span className="text-xs font-normal text-ink-muted">optional</span> : null}
    </label>
  );
}
