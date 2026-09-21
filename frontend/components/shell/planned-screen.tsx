import Link from "next/link";
import * as React from "react";

import { PageHeader, PageShell } from "@/components/shell/page-header";
import { Badge } from "@/components/ui/badge";
import { buttonStyles } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";

export interface PlannedScreenProps {
  title: string;
  description: string;
  /** The milestone week from plan.md §11.2, so the state is dated, not vague. */
  week: string;
  icon: React.ReactNode;
  /** The two or three things this screen will do, in the person's words. */
  points: readonly string[];
}

/**
 * An honest placeholder. It says what the screen will do and when, rather than
 * pretending to be finished — a demo should never imply working software.
 */
export function PlannedScreen({ title, description, week, icon, points }: PlannedScreenProps) {
  return (
    <PageShell>
      <PageHeader
        title={title}
        description={description}
        action={
          <Badge tone="outline" mono>
            {week}
          </Badge>
        }
      />
      <EmptyState
        icon={icon}
        title="Not built yet"
        description="The design system, the shell and the Recognition card are finished. This screen comes with its API."
        action={
          <Link href="/app/recognitions" className={buttonStyles("secondary", "md")}>
            See a Recognition
          </Link>
        }
      />
      <ul className="mt-8 flex flex-col gap-3">
        {points.map((point) => (
          <li key={point} className="flex gap-3 border-b border-line pb-3 last:border-0">
            <span aria-hidden="true" className="mt-[0.7em] h-px w-4 shrink-0 bg-line-strong" />
            <span className="text-base leading-relaxed text-ink-secondary">{point}</span>
          </li>
        ))}
      </ul>
    </PageShell>
  );
}
