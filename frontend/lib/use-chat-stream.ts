"use client";

import * as React from "react";

import { ApiError, errorMessage, postStream } from "@/lib/api";
import { messagesPath } from "@/lib/endpoints";
import type { Uuid } from "@/lib/types";

/** The turn currently in flight, rendered on top of the saved thread. */
export interface PendingTurn {
  clientMessageId: string;
  content: string;
  /** Allocated by the server on `message.user`; null until then. */
  userSeq: number | null;
  /** What has arrived of the reply so far. */
  text: string;
  thinking: boolean;
  status: "sending" | "streaming" | "failed";
  error: string | null;
}

export interface ChatStream {
  pending: PendingTurn | null;
  /** True from the moment Send is pressed until the reply is saved. */
  busy: boolean;
  send: (content: string) => void;
  /** Re-send the failed turn under the same client id, so nothing duplicates. */
  retry: () => void;
  stop: () => void;
  /** Drop a failed turn without sending it again. */
  discard: () => void;
}

export interface UseChatStreamOptions {
  conversationId: Uuid | null;
  /** Called once the reply is complete, so the thread can be re-read. */
  onFinished: () => void;
  /** A frame the stream could not recover from, for the toast. */
  onError?: (message: string, requestId?: string) => void;
}

function newClientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * One turn of chat over `POST /conversations/{id}/messages`.
 *
 * EventSource cannot POST, so the body is read frame by frame through
 * `postStream`. The `client_message_id` is generated once per turn and reused on
 * retry: that is what lets the API recognise a resend instead of storing the
 * same sentence twice.
 */
export function useChatStream({
  conversationId,
  onFinished,
  onError,
}: UseChatStreamOptions): ChatStream {
  const [pending, setPending] = React.useState<PendingTurn | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const finishedRef = React.useRef(onFinished);
  const errorRef = React.useRef(onError);
  // Read by `retry`: a side effect must not live inside a state updater, which
  // React runs twice in development and would send the turn twice.
  const pendingRef = React.useRef<PendingTurn | null>(null);
  finishedRef.current = onFinished;
  errorRef.current = onError;
  pendingRef.current = pending;

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const run = React.useCallback(
    (turn: PendingTurn) => {
      if (!conversationId) return;
      const controller = new AbortController();
      abortRef.current = controller;
      setPending({ ...turn, status: "sending", text: "", thinking: false, error: null });

      let finished = false;

      postStream(
        messagesPath(conversationId),
        { content: turn.content, client_message_id: turn.clientMessageId },
        (event, data) => {
          const payload = (data ?? {}) as Record<string, unknown>;
          if (event === "message.user") {
            const seq = typeof payload.seq === "number" ? payload.seq : null;
            setPending((current) => (current ? { ...current, userSeq: seq } : current));
          } else if (event === "thinking") {
            setPending((current) =>
              current ? { ...current, thinking: true, status: "streaming" } : current,
            );
          } else if (event === "delta") {
            const text = typeof payload.text === "string" ? payload.text : "";
            setPending((current) =>
              current
                ? { ...current, text: current.text + text, thinking: false, status: "streaming" }
                : current,
            );
          } else if (event === "message.assistant") {
            finished = true;
          } else if (event === "error") {
            const detail =
              typeof payload.detail === "string"
                ? payload.detail
                : "The reply stopped before it finished.";
            setPending((current) =>
              current ? { ...current, status: "failed", error: detail, thinking: false } : current,
            );
            errorRef.current?.(detail);
          }
        },
        { signal: controller.signal },
      )
        .then(() => {
          if (finished) {
            setPending(null);
            finishedRef.current();
          } else {
            // The body ended without message.assistant: treat it as retryable.
            setPending((current) =>
              current && current.status !== "failed"
                ? { ...current, status: "failed", error: "The reply was cut off.", thinking: false }
                : current,
            );
          }
        })
        .catch((cause: unknown) => {
          if (cause instanceof DOMException && cause.name === "AbortError") {
            // Stop was pressed. Whatever arrived is kept by the server as partial.
            setPending(null);
            finishedRef.current();
            return;
          }
          const message = errorMessage(cause);
          setPending((current) =>
            current ? { ...current, status: "failed", error: message, thinking: false } : current,
          );
          errorRef.current?.(
            message,
            cause instanceof ApiError ? cause.requestId : undefined,
          );
        })
        .finally(() => {
          if (abortRef.current === controller) abortRef.current = null;
        });
    },
    [conversationId],
  );

  const send = React.useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || !conversationId) return;
      run({
        clientMessageId: newClientId(),
        content: trimmed,
        userSeq: null,
        text: "",
        thinking: false,
        status: "sending",
        error: null,
      });
    },
    [conversationId, run],
  );

  const retry = React.useCallback(() => {
    const current = pendingRef.current;
    if (current) run(current);
  }, [run]);

  const stop = React.useCallback(() => abortRef.current?.abort(), []);
  const discard = React.useCallback(() => setPending(null), []);

  return {
    pending,
    busy: pending !== null && pending.status !== "failed",
    send,
    retry,
    stop,
    discard,
  };
}
