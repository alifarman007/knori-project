"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { Composer } from "@/components/chat/composer";
import { InlineRecognition } from "@/components/chat/inline-recognition";
import { MessageRow } from "@/components/chat/message-row";
import { RecognitionChip } from "@/components/chat/recognition-chip";
import { ThinkingIndicator } from "@/components/chat/thinking-indicator";
import { WelcomeBackStrip } from "@/components/chat/welcome-back-strip";
import { useLiveEvent } from "@/components/live/live-events";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { SkeletonText } from "@/components/ui/skeleton";
import { conversations as api } from "@/lib/endpoints";
import { messageAnchorId, parseHighlight } from "@/lib/highlight";
import { keys } from "@/lib/query-keys";
import type { Conversation, Message, Uuid, WelcomeBack } from "@/lib/types";
import { useChatStream } from "@/lib/use-chat-stream";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

export interface ChatThreadProps {
  conversation: Conversation;
  opener?: string | null;
  welcomeBack?: WelcomeBack | null;
}

const RECOGNITION_ANCHOR = "new-recognition";

/** A local stand-in for the assistant's reply while it is still arriving. */
function streamingMessage(seq: number, text: string): Message {
  return {
    id: "streaming",
    seq,
    role: "assistant",
    content: text,
    status: "streaming",
    created_at: new Date().toISOString(),
  };
}

export function ChatThread({ conversation, opener, welcomeBack }: ChatThreadProps) {
  const queryClient = useQueryClient();
  const reportError = useErrorToast();
  const searchParams = useSearchParams();
  const target = React.useMemo(() => parseHighlight(searchParams), [searchParams]);

  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const bottomRef = React.useRef<HTMLDivElement | null>(null);
  const atBottomRef = React.useRef(true);
  const [chipFor, setChipFor] = React.useState<Uuid | null>(null);

  const query = useQuery({
    queryKey: [...keys.messages(conversation.id), target?.seq ?? null],
    queryFn: () =>
      api.messages(
        conversation.id,
        target ? { around_seq: target.seq, limit: 100 } : { limit: 100 },
      ),
  });

  const stream = useChatStream({
    conversationId: conversation.id,
    onFinished: () => {
      void queryClient.invalidateQueries({ queryKey: keys.messages(conversation.id) });
      void queryClient.invalidateQueries({ queryKey: keys.conversations });
    },
    onError: (message) => reportError(new Error(message), "The reply did not finish"),
  });

  // A card can arrive for this conversation while the person is reading it.
  useLiveEvent((event) => {
    if (event.event !== "recognition.created") return;
    if (event.data.conversation_id && event.data.conversation_id !== conversation.id) return;
    void queryClient.invalidateQueries({ queryKey: keys.messages(conversation.id) });
    setChipFor(event.data.recognition_id);
  });

  const messages = query.data?.messages ?? [];
  const events = query.data?.events ?? [];
  const lastSeq = messages.length > 0 ? (messages[messages.length - 1]?.seq ?? 0) : 0;

  /* ------------------------------------------------------------ scrolling */

  function onScroll() {
    const node = scrollRef.current;
    if (!node) return;
    atBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
  }

  // New content: follow it down, but only if they had not scrolled up to read.
  React.useEffect(() => {
    if (!atBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, stream.pending?.text, stream.pending?.clientMessageId]);

  // A deep link wins over "stay at the bottom": that is the whole point of it.
  const jumpedTo = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!target || query.isPending) return;
    const anchorKey = `${conversation.id}:${target.seq}:${target.start ?? ""}`;
    if (jumpedTo.current === anchorKey) return;
    const node = document.getElementById(messageAnchorId(target.seq));
    if (!node) return;
    jumpedTo.current = anchorKey;
    atBottomRef.current = false;
    node.scrollIntoView({ block: "center", behavior: "smooth" });
    node.focus?.();
  }, [target, query.isPending, conversation.id]);

  /* -------------------------------------------------------------- render */

  const pending = stream.pending;
  const cardsAfter = new Map<number, string[]>();
  for (const event of events) {
    const list = cardsAfter.get(event.after_seq) ?? [];
    list.push(event.recognition_id);
    cardsAfter.set(event.after_seq, list);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
          {welcomeBack ? <WelcomeBackStrip welcome={welcomeBack} className="mb-6" /> : null}

          {conversation.is_incognito ? (
            <Alert tone="info" className="mb-6">
              This conversation is not remembered. Nothing said here becomes memory, and nothing in
              it can become evidence for a Recognition.
            </Alert>
          ) : null}

          {query.isPending ? (
            <div className="flex flex-col gap-8" aria-busy="true">
              <SkeletonText lines={2} />
              <SkeletonText lines={4} />
              <SkeletonText lines={3} />
            </div>
          ) : query.isError ? (
            <Alert tone="danger" title="This conversation could not be loaded">
              <Button
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={() => void query.refetch()}
              >
                Try again
              </Button>
            </Alert>
          ) : (
            <div className="flex flex-col gap-7">
              {opener && messages.length === 0 ? (
                <p className="knori-prose text-ink-secondary">{opener}</p>
              ) : null}

              {messages.length === 0 && !opener && !pending ? (
                <div className="py-10 text-center">
                  <p className="font-serif text-xl text-ink">What is going on today?</p>
                  <p className="mx-auto mt-2 max-w-sm text-base text-ink-muted">
                    Talk the way you would to somebody who has time. KnoRI keeps what you tell it,
                    and only says what it noticed once it can show you why.
                  </p>
                </div>
              ) : null}

              {messages.map((message) => (
                <React.Fragment key={`${message.id}-${message.seq}`}>
                  <MessageRow
                    message={message}
                    highlight={
                      target &&
                      target.seq === message.seq &&
                      target.start !== null &&
                      target.end !== null
                        ? { start: target.start, end: target.end }
                        : null
                    }
                  />
                  {(cardsAfter.get(message.seq) ?? []).map((id) => (
                    <InlineRecognition
                      key={id}
                      recognitionId={id}
                      anchorId={id === chipFor ? RECOGNITION_ANCHOR : undefined}
                    />
                  ))}
                </React.Fragment>
              ))}

              {pending ? (
                <>
                  <MessageRow
                    message={{
                      id: pending.clientMessageId,
                      seq: pending.userSeq ?? lastSeq + 1,
                      role: "user",
                      content: pending.content,
                      status: pending.status === "failed" ? "failed" : "complete",
                      created_at: new Date().toISOString(),
                    }}
                  />
                  {pending.thinking && !pending.text ? (
                    <ThinkingIndicator />
                  ) : pending.text ? (
                    <MessageRow
                      message={streamingMessage(pending.userSeq ?? lastSeq + 2, pending.text)}
                    />
                  ) : pending.status === "sending" ? (
                    <ThinkingIndicator label="Sending" />
                  ) : null}
                </>
              ) : null}
            </div>
          )}

          <div ref={bottomRef} className="h-1" />
        </div>
      </div>

      {chipFor ? (
        <div className="pointer-events-none sticky bottom-2 z-10 flex justify-center px-4">
          <RecognitionChip
            onOpen={() => {
              document
                .getElementById(RECOGNITION_ANCHOR)
                ?.scrollIntoView({ block: "center", behavior: "smooth" });
              setChipFor(null);
            }}
            onDismiss={() => setChipFor(null)}
          />
        </div>
      ) : null}

      <Composer
        // The mobile tab bar is fixed over the bottom of the viewport.
        className="pb-[4.5rem] md:pb-0"
        streaming={stream.busy}
        disabled={query.isError}
        onSend={stream.send}
        onStop={stream.stop}
        placeholder={
          conversation.is_incognito
            ? "This one is not remembered."
            : "Say anything. KnoRI will remember it."
        }
        notice={
          pending?.status === "failed" ? (
            <div
              className={cn(
                "flex flex-wrap items-center gap-3 rounded-md border border-danger/30",
                "bg-danger-soft px-3 py-2 text-sm text-ink",
              )}
              role="alert"
            >
              <span className="min-w-0 flex-1">{pending.error ?? "That message did not send."}</span>
              <Button size="sm" variant="secondary" onClick={stream.retry}>
                Try again
              </Button>
              <Button size="sm" variant="ghost" onClick={stream.discard}>
                Discard
              </Button>
            </div>
          ) : null
        }
      />
    </div>
  );
}
