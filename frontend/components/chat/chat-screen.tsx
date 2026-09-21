"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ChatThread } from "@/components/chat/chat-thread";
import { ConversationList } from "@/components/chat/conversation-list";
import { IconIncognito, IconMenu } from "@/components/icons";
import { OfflineBanner } from "@/components/live/offline-banner";
import { Badge } from "@/components/ui/badge";
import { Sheet } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { conversations as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { Conversation, ConversationStart, Uuid } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

/** Plan §5.5: reopen the last conversation if it is still fresh. */
const CONTINUITY_WINDOW_MS = 24 * 60 * 60 * 1000;

function startKey(id: Uuid) {
  return ["conversation-start", id] as const;
}

function isRecent(conversation: Conversation): boolean {
  const stamp = conversation.last_message_at ?? conversation.created_at;
  const at = Date.parse(stamp);
  if (Number.isNaN(at)) return false;
  return Date.now() - at < CONTINUITY_WINDOW_MS;
}

export interface ChatScreenProps {
  /** `null` on `/app/chat`, which then decides where to send them. */
  conversationId: Uuid | null;
}

export function ChatScreen({ conversationId }: ChatScreenProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reportError = useErrorToast();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const startedRef = React.useRef(false);

  const list = useQuery({
    queryKey: keys.conversations,
    queryFn: () => api.list(),
  });

  const items = React.useMemo(
    () => (list.data?.items ?? []).filter((item) => item.archived_at === null),
    [list.data],
  );

  const create = React.useCallback(
    async (incognito: boolean) => {
      setCreating(true);
      try {
        const start = await api.create(incognito);
        queryClient.setQueryData<ConversationStart>(startKey(start.conversation.id), start);
        await queryClient.invalidateQueries({ queryKey: keys.conversations });
        setDrawerOpen(false);
        router.push(`/app/chat/${start.conversation.id}`);
      } catch (error) {
        reportError(error, "A new conversation could not be started");
      } finally {
        setCreating(false);
      }
    },
    [queryClient, reportError, router],
  );

  // Continuity: land in the last conversation, or open a fresh one.
  React.useEffect(() => {
    if (conversationId || list.isPending || startedRef.current) return;
    startedRef.current = true;
    const newest = items.find((item) => item.kind === "chat");
    if (newest && isRecent(newest)) {
      router.replace(`/app/chat/${newest.id}`);
      return;
    }
    void create(false);
  }, [conversationId, list.isPending, items, router, create]);

  const active = conversationId ? items.find((item) => item.id === conversationId) : undefined;

  const detail = useQuery({
    queryKey: keys.conversation(conversationId ?? "none"),
    queryFn: () => api.get(conversationId as Uuid),
    enabled: Boolean(conversationId) && !active && !list.isPending,
  });

  const conversation = active ?? detail.data ?? null;
  const start = conversationId
    ? queryClient.getQueryData<ConversationStart>(startKey(conversationId))
    : undefined;

  const sidebar = (
    <ConversationList
      conversations={items}
      activeId={conversationId}
      loading={list.isPending}
      creating={creating}
      onCreate={create}
      onPick={() => setDrawerOpen(false)}
    />
  );

  return (
    // The shell pads `main` for the mobile tab bar; chat wants the full height.
    <div className="-mb-24 flex h-[calc(100dvh-3.5rem)] md:-mb-10">
      <aside className="hidden w-[272px] shrink-0 border-r border-line md:block">{sidebar}</aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />

        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-4 sm:px-6">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className={cn(
              "-ml-1 grid size-8 place-items-center rounded-md text-ink-muted md:hidden",
              "transition-colors hover:bg-sunken hover:text-ink",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
            )}
            aria-label="Conversations"
          >
            <IconMenu className="size-5" />
          </button>

          <h1 className="min-w-0 flex-1 truncate font-serif text-md text-ink">
            {conversation?.title ?? "New conversation"}
          </h1>

          {conversation?.is_incognito ? (
            <Badge tone="outline" mono>
              <IconIncognito className="size-3.5" />
              not remembered
            </Badge>
          ) : null}
        </header>

        {conversation ? (
          <ChatThread
            key={conversation.id}
            conversation={conversation}
            opener={start?.opener ?? null}
            welcomeBack={start?.welcome_back ?? null}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <Spinner label="Opening your conversation" className="text-ink-muted" />
          </div>
        )}
      </div>

      <Sheet
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        side="left"
        title="Conversations"
        className="sm:max-w-xs"
      >
        <div className="-mx-5 h-full sm:-mx-6">{sidebar}</div>
      </Sheet>
    </div>
  );
}
