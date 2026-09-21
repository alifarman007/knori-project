"use client";

import Link from "next/link";
import * as React from "react";

import { IconIncognito, IconPlus } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeDate, truncate } from "@/lib/format";
import type { Conversation, Uuid } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ConversationListProps {
  conversations: readonly Conversation[];
  activeId: Uuid | null;
  loading: boolean;
  creating: boolean;
  /** `incognito` comes from the toggle under the button. */
  onCreate: (incognito: boolean) => void;
  /** Closes the drawer on phones after a conversation is picked. */
  onPick?: () => void;
  className?: string;
}

function title(conversation: Conversation): string {
  if (conversation.title) return truncate(conversation.title, 44);
  return conversation.kind === "onboarding" ? "Your first answers" : "Untitled conversation";
}

/**
 * Every conversation, newest first.
 *
 * The incognito toggle lives next to "New conversation" and nowhere else: it is
 * a property of a conversation at the moment it is created, and letting someone
 * flip it mid-thread would mean quietly un-remembering things already said.
 */
export function ConversationList({
  conversations,
  activeId,
  loading,
  creating,
  onCreate,
  onPick,
  className,
}: ConversationListProps) {
  const [incognito, setIncognito] = React.useState(false);
  const reactId = React.useId();
  const toggleId = `inc${reactId.replace(/:/g, "")}`;

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="border-b border-line px-3 py-3">
        <Button
          variant="secondary"
          fullWidth
          loading={creating}
          loadingText="Starting…"
          onClick={() => onCreate(incognito)}
        >
          <IconPlus className="size-4" />
          New conversation
        </Button>

        <label
          htmlFor={toggleId}
          className="mt-2.5 flex cursor-pointer items-start gap-2 rounded-sm px-1 py-1 text-sm text-ink-muted"
        >
          <input
            id={toggleId}
            type="checkbox"
            checked={incognito}
            onChange={(event) => setIncognito(event.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-[var(--knori-accent)]"
          />
          <span>
            <span className="flex items-center gap-1.5 font-medium text-ink-secondary">
              <IconIncognito className="size-4" />
              Do not remember this one
            </span>
            <span className="mt-0.5 block text-xs">
              Nothing said in it becomes memory or evidence.
            </span>
          </span>
        </label>
      </div>

      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading ? (
          <ul className="flex flex-col gap-1 p-1">
            {[0, 1, 2, 3, 4].map((index) => (
              <li key={index}>
                <Skeleton className="h-[52px] w-full rounded-md" />
              </li>
            ))}
          </ul>
        ) : conversations.length === 0 ? (
          <p className="px-3 py-6 text-sm leading-relaxed text-ink-muted">
            Nothing here yet. Start a conversation and KnoRI begins keeping track of what you tell
            it.
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((conversation) => {
              const active = conversation.id === activeId;
              return (
                <li key={conversation.id}>
                  <Link
                    href={`/app/chat/${conversation.id}`}
                    onClick={onPick}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "block rounded-md px-3 py-2.5 transition-colors",
                      "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus",
                      active
                        ? "bg-sunken text-ink"
                        : "text-ink-secondary hover:bg-sunken/70 hover:text-ink",
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      {conversation.is_incognito ? (
                        <IconIncognito className="size-3.5 shrink-0 text-ink-muted" />
                      ) : null}
                      <span className="truncate text-base">{title(conversation)}</span>
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
                      <span>
                        {relativeDate(conversation.last_message_at ?? conversation.created_at)}
                      </span>
                      {conversation.message_count > 0 ? (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="tabular-nums">{conversation.message_count}</span>
                        </>
                      ) : null}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </div>
  );
}
