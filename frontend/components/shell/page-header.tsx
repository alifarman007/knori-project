import * as React from "react";

import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function PageHeader({ title, description, action, className }: PageHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4 pb-6 pt-8", className)}>
      <div className="min-w-0">
        <h1 className="text-2xl">{title}</h1>
        {description ? (
          <p className="mt-2 max-w-2xl text-base text-ink-muted">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/** The 16px-gutter column every app page sits in. */
export function PageShell({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("knori-gutter mx-auto w-full max-w-3xl", className)}>{children}</div>;
}
