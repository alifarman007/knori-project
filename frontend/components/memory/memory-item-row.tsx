"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { IconChevronDown, IconExternal, IconPencil, IconPin, IconTrash } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { memory } from "@/lib/endpoints";
import { formatDate } from "@/lib/format";
import { MEMORY_SOURCE_LABEL, MEMORY_STATUS_LABEL } from "@/lib/labels";
import { keys } from "@/lib/query-keys";
import type { MemoryItem, MemorySource } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface MemoryItemRowProps {
  item: MemoryItem;
  onEdit: (item: MemoryItem) => void;
  onTogglePin: (item: MemoryItem) => void;
  onRetract: (item: MemoryItem) => void;
  busy?: boolean;
}

function deepLink(source: MemorySource): string | null {
  if (!source.conversation_id || source.seq === null) return null;
  const params = new URLSearchParams({ m: String(source.seq) });
  if (source.quote_start !== null && source.quote_end !== null) {
    params.set("hl", `${source.quote_start}-${source.quote_end}`);
  }
  return `/app/chat/${source.conversation_id}?${params.toString()}`;
}

function Sources({ item }: { item: MemoryItem }) {
  // Fetched only when opened: most rows are never expanded.
  const query = useQuery({
    queryKey: keys.memorySources(item.id),
    queryFn: () => memory.sources(item.id),
    enabled: !item.sources,
    initialData: item.sources,
  });

  if (query.isPending) return <Skeleton className="mt-3 h-12 w-full" />;

  const sources = query.data ?? [];
  if (sources.length === 0) {
    return (
      <p className="mt-3 text-sm text-ink-muted">
        {item.source === "user_added"
          ? "You wrote this yourself, so there is no quote behind it."
          : "The message this came from is gone."}
      </p>
    );
  }

  return (
    <ul className="mt-3 flex flex-col gap-3">
      {sources.map((source) => {
        const href = deepLink(source);
        return (
          <li key={source.id} className="border-l-2 border-accent-line pl-3">
            <blockquote className="font-serif text-base leading-relaxed text-ink">
              &ldquo;{source.quote_text}&rdquo;
            </blockquote>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-ink-muted">
              <time dateTime={source.message_created_at}>
                {formatDate(source.message_created_at)}
              </time>
              {source.conversation_title ? (
                <>
                  <span aria-hidden="true">·</span>
                  <span className="truncate">{source.conversation_title}</span>
                </>
              ) : null}
              {href ? (
                <>
                  <span aria-hidden="true">·</span>
                  <Link
                    href={href}
                    className="inline-flex items-center gap-1 text-accent underline decoration-accent-line underline-offset-4"
                  >
                    open in chat
                    <IconExternal className="size-3" />
                  </Link>
                </>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * One thing KnoRI remembers, with the quote it came from.
 *
 * Retracting is a soft delete on purpose: the row stays with `status=retracted`
 * so the person can see what they took back, and so nothing silently
 * reappears the next time the same sentence is extracted.
 */
export function MemoryItemRow({
  item,
  onEdit,
  onTogglePin,
  onRetract,
  busy = false,
}: MemoryItemRowProps) {
  const [open, setOpen] = React.useState(false);
  const reactId = React.useId();
  const panelId = `ms${reactId.replace(/:/g, "")}`;
  const retracted = item.status === "retracted";

  return (
    <li
      className={cn(
        "group border-b border-line py-4 last:border-0",
        retracted && "opacity-60",
        busy && "pointer-events-none opacity-50",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              "font-serif text-md leading-relaxed text-ink",
              retracted && "line-through decoration-line-strong",
            )}
          >
            {item.statement}
          </p>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-muted">
            <span className="knori-eyebrow">{MEMORY_SOURCE_LABEL[item.source]}</span>
            <span aria-hidden="true">·</span>
            <time dateTime={item.first_seen_at}>{formatDate(item.first_seen_at)}</time>
            {item.confirmations > 1 ? (
              <>
                <span aria-hidden="true">·</span>
                <span>said {item.confirmations} times</span>
              </>
            ) : null}
            {item.pinned ? (
              <Badge tone="accent" mono>
                pinned
              </Badge>
            ) : null}
            {item.status !== "active" ? (
              <Badge tone="outline" mono>
                {MEMORY_STATUS_LABEL[item.status]}
              </Badge>
            ) : null}
            {item.sensitive_category ? (
              <Badge tone="outline" mono>
                never used as evidence
              </Badge>
            ) : null}
          </div>
        </div>

        {!retracted ? (
          <div className="flex shrink-0 items-center gap-0.5">
            <RowButton
              label={item.pinned ? "Unpin this" : "Pin this so KnoRI always sees it"}
              onClick={() => onTogglePin(item)}
              active={item.pinned}
            >
              <IconPin className="size-4" />
            </RowButton>
            <RowButton label="Edit this" onClick={() => onEdit(item)}>
              <IconPencil className="size-4" />
            </RowButton>
            <RowButton label="Retract this" onClick={() => onRetract(item)} danger>
              <IconTrash className="size-4" />
            </RowButton>
          </div>
        ) : null}
      </div>

      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "mt-2 inline-flex items-center gap-1.5 rounded-sm text-sm text-ink-muted",
          "transition-colors hover:text-ink",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        )}
      >
        <IconChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        {open ? "hide where this came from" : "where this came from"}
      </button>

      <div id={panelId} hidden={!open}>
        {open ? <Sources item={item} /> : null}
      </div>
    </li>
  );
}

function RowButton({
  label,
  onClick,
  children,
  active,
  danger,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  active?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={cn(
        "grid size-8 place-items-center rounded-sm transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100",
        active ? "text-accent sm:opacity-100" : "text-ink-muted hover:text-ink",
        danger && "hover:text-danger",
      )}
    >
      {children}
    </button>
  );
}
