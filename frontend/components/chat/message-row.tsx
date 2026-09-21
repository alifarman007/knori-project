"use client";

import * as React from "react";

import { IconTrash } from "@/components/icons";
import { formatTime, relativeDate } from "@/lib/format";
import { messageAnchorId, splitForHighlight } from "@/lib/highlight";
import type { Message } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface MessageRowProps {
  message: Message;
  /** Character range to mark, from a `?hl=` deep link. */
  highlight?: { start: number; end: number } | null;
  onDelete?: (seq: number) => void;
  className?: string;
}

/**
 * One turn in the thread.
 *
 * KnoRI's own words are set in the serif, the person's in the sans — the same
 * split the Recognition card uses, so "this is what you said" and "this is what
 * KnoRI said" never need a label to tell them apart.
 */
export const MessageRow = React.memo(function MessageRow({
  message,
  highlight = null,
  onDelete,
  className,
}: MessageRowProps) {
  const isUser = message.role === "user";
  const segments = splitForHighlight(
    message.content,
    highlight?.start ?? null,
    highlight?.end ?? null,
  );

  const body = segments.map((segment, index) =>
    segment.marked ? (
      <mark
        key={index}
        className="rounded-[3px] bg-accent-soft px-0.5 text-ink decoration-accent decoration-2 underline-offset-4"
      >
        {segment.text}
      </mark>
    ) : (
      <React.Fragment key={index}>{segment.text}</React.Fragment>
    ),
  );

  return (
    <article
      id={messageAnchorId(message.seq)}
      data-seq={message.seq}
      data-role={message.role}
      className={cn("group scroll-mt-24", isUser && "flex justify-end", className)}
    >
      <div className={cn("min-w-0", isUser ? "max-w-[min(42rem,88%)]" : "w-full")}>
        {isUser ? (
          <div
            className={cn(
              "rounded-lg rounded-br-sm border border-line bg-sunken px-4 py-3",
              "whitespace-pre-wrap break-words text-base leading-relaxed text-ink",
              highlight && "border-accent-line ring-1 ring-accent-line",
            )}
          >
            {body}
          </div>
        ) : (
          <div
            className={cn(
              "knori-prose whitespace-pre-wrap break-words text-ink-secondary",
              message.status === "failed" && "text-ink-muted line-through decoration-line-strong",
            )}
          >
            {body}
            {message.status === "streaming" ? (
              <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-accent" />
            ) : null}
          </div>
        )}

        <div
          className={cn(
            "mt-1.5 flex items-center gap-2 text-xs text-ink-muted",
            isUser && "justify-end",
          )}
        >
          {message.status === "partial" ? (
            <span className="knori-eyebrow text-danger">cut off</span>
          ) : null}
          {message.status === "failed" ? (
            <span className="knori-eyebrow text-danger">did not send</span>
          ) : null}
          <time
            dateTime={message.created_at}
            className="opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
          >
            {relativeDate(message.created_at)} · {formatTime(message.created_at)}
          </time>
          {isUser && onDelete ? (
            <button
              type="button"
              onClick={() => onDelete(message.seq)}
              className={cn(
                "rounded-sm p-1 text-ink-muted opacity-0 transition-opacity",
                "hover:text-danger focus-visible:opacity-100 group-hover:opacity-100",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
              )}
              aria-label={`Delete your message from ${relativeDate(message.created_at)}`}
            >
              <IconTrash className="size-3.5" />
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
});
