import * as React from "react";

import { cn } from "@/lib/utils";

export interface SettingSectionProps {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  /** A number in the eyebrow keeps a long settings page navigable. */
  eyebrow?: string;
  className?: string;
  id?: string;
}

export function SettingSection({
  title,
  description,
  children,
  eyebrow,
  className,
  id,
}: SettingSectionProps) {
  const headingId = id ? `${id}-title` : undefined;

  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className={cn("border-t border-line py-8 first:border-0", className)}
    >
      <div className="grid gap-6 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:gap-10">
        <div>
          {eyebrow ? <p className="knori-eyebrow mb-2">{eyebrow}</p> : null}
          <h2 id={headingId} className="font-serif text-lg text-ink">
            {title}
          </h2>
          {description ? (
            <p className="mt-2 text-base leading-relaxed text-ink-muted">{description}</p>
          ) : null}
        </div>
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}
