"use client";

import { IconCheck, IconClose, IconPencil } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import type { FeedbackAction, RecognitionState } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface FeedbackBarProps {
  state: RecognitionState;
  onAction: (action: FeedbackAction) => void;
  /** The action currently in flight, so only that button spins. */
  pending?: FeedbackAction | null;
  disabled?: boolean;
  resolvedAt?: string | null;
  className?: string;
}

const RESOLVED_WORDS: Partial<Record<RecognitionState, string>> = {
  accepted: "You said this is right.",
  corrected: "You corrected this. KnoRI reasons differently now.",
  rejected: "You said this is not true. KnoRI will not raise it again.",
  dismissed: "You set this aside.",
  withdrawn: "KnoRI withdrew this after the evidence changed.",
};

/**
 * Accept · Correct · Reject · Dismiss.
 *
 * All four are equally reachable — there is no primary action, because the
 * product has no preference about which answer it gets. The bar is replaced by
 * a plain sentence once the person has answered.
 */
export function FeedbackBar({
  state,
  onAction,
  pending = null,
  disabled = false,
  resolvedAt,
  className,
}: FeedbackBarProps) {
  const resolved = RESOLVED_WORDS[state];

  if (resolved) {
    return (
      <p className={cn("flex flex-wrap items-center gap-x-2 text-sm text-ink-muted", className)}>
        <span>{resolved}</span>
        {resolvedAt ? <time dateTime={resolvedAt}>{formatDate(resolvedAt)}</time> : null}
      </p>
    );
  }

  const busy = disabled || pending !== null;

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <Button
        size="sm"
        variant="secondary"
        loading={pending === "accept"}
        disabled={busy && pending !== "accept"}
        onClick={() => onAction("accept")}
      >
        <IconCheck className="size-4" />
        That&rsquo;s right
      </Button>
      <Button
        size="sm"
        variant="secondary"
        loading={pending === "correct"}
        disabled={busy && pending !== "correct"}
        onClick={() => onAction("correct")}
      >
        <IconPencil className="size-4" />
        Not quite
      </Button>
      <Button
        size="sm"
        variant="ghost"
        loading={pending === "reject"}
        disabled={busy && pending !== "reject"}
        onClick={() => onAction("reject")}
      >
        <IconClose className="size-4" />
        Not true
      </Button>
      <Button
        size="sm"
        variant="ghost"
        loading={pending === "dismiss"}
        disabled={busy && pending !== "dismiss"}
        onClick={() => onAction("dismiss")}
        className="ml-auto text-ink-muted"
      >
        Not now
      </Button>
    </div>
  );
}
