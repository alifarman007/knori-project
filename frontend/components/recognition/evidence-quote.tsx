import Link from "next/link";

import { IconExternal } from "@/components/icons";
import { formatDate } from "@/lib/format";
import type { ProvenanceItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface EvidenceQuoteProps {
  item: ProvenanceItem;
  className?: string;
  /**
   * Where "open in chat" goes. Omit it (or return null) and the quote is shown
   * without a link — which is what the landing page sample does.
   */
  hrefFor?: (item: ProvenanceItem) => string | null;
}

const ROLE_LABEL: Record<ProvenanceItem["role"], string> = {
  supports: "you said",
  contradicts: "pulls against this",
  context: "context",
};

/**
 * One verbatim thing the person said, with the day they said it.
 *
 * Two states matter beyond the happy path:
 *   - `scrubbed`: they deleted the message, so the text is gone but the row
 *     stays. We say so plainly rather than hiding the gap.
 *   - `kind === "assertion"`: this is their own correction being used as
 *     evidence, which deserves a different label from "you said".
 */
export function EvidenceQuote({ item, className, hrefFor }: EvidenceQuoteProps) {
  const href = hrefFor?.(item) ?? null;
  const isCorrection = item.kind === "assertion";
  const isContradiction = item.role === "contradicts";

  return (
    <li
      className={cn(
        "relative pl-4",
        "before:absolute before:left-0 before:top-1 before:bottom-1 before:w-0.5 before:rounded-full",
        item.scrubbed
          ? "before:bg-line-strong"
          : isContradiction
            ? "before:bg-danger/50"
            : "before:bg-accent-line",
        className,
      )}
    >
      {item.scrubbed ? (
        <p className="font-serif text-md italic text-ink-muted">
          You deleted this message, so the words are gone. KnoRI kept the fact that it counted.
        </p>
      ) : (
        <blockquote className="font-serif text-md leading-relaxed text-ink">
          <span aria-hidden="true" className="text-accent">
            &ldquo;
          </span>
          {item.quote_text}
          <span aria-hidden="true" className="text-accent">
            &rdquo;
          </span>
        </blockquote>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
        <span className="knori-eyebrow not-italic">
          {isCorrection ? "your correction" : ROLE_LABEL[item.role]}
        </span>
        {item.message_created_at ? (
          <>
            <span aria-hidden="true">·</span>
            <time dateTime={item.message_created_at}>{formatDate(item.message_created_at)}</time>
          </>
        ) : null}
        {item.conversation_title ? (
          <>
            <span aria-hidden="true">·</span>
            <span className="truncate">{item.conversation_title}</span>
          </>
        ) : null}
        {href ? (
          <>
            <span aria-hidden="true">·</span>
            <Link
              href={href}
              className="inline-flex items-center gap-1 text-accent underline decoration-accent-line underline-offset-4 transition-colors hover:text-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              open in chat
              <IconExternal className="size-3.5" />
            </Link>
          </>
        ) : null}
      </div>
    </li>
  );
}

/** The deep link that highlights the exact span in the thread (plan §8). */
export function chatDeepLink(item: ProvenanceItem): string | null {
  if (!item.conversation_id || item.seq === null) return null;
  const params = new URLSearchParams({ m: String(item.seq) });
  if (item.quote_start !== null && item.quote_end !== null) {
    params.set("hl", `${item.quote_start}-${item.quote_end}`);
  }
  return `/app/chat/${item.conversation_id}?${params.toString()}`;
}
