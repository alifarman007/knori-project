"use client";

import * as React from "react";

import { IconSend, IconStop } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** The API caps a message at 8k characters; the counter appears well before it. */
export const MAX_MESSAGE_LENGTH = 8_000;
const COUNTER_FROM = MAX_MESSAGE_LENGTH - 500;

export interface ComposerProps {
  onSend: (content: string) => void;
  onStop: () => void;
  /** True while a reply is streaming: Send becomes Stop. */
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** Shown above the box, e.g. the retry line for a failed turn. */
  notice?: React.ReactNode;
  className?: string;
}

/**
 * Enter sends, Shift+Enter starts a new line.
 *
 * That pairing is what people expect from a chat, but it also means Enter can
 * destroy a half-written paragraph, so the box grows to twelve lines before it
 * scrolls and the text is never cleared until the send has actually started.
 */
export function Composer({
  onSend,
  onStop,
  streaming,
  disabled = false,
  placeholder = "Say anything. KnoRI will remember it.",
  notice,
  className,
}: ComposerProps) {
  const [value, setValue] = React.useState("");
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const reactId = React.useId();
  const countId = `cc${reactId.replace(/:/g, "")}`;

  const trimmed = value.trim();
  const tooLong = value.length > MAX_MESSAGE_LENGTH;
  const canSend = trimmed.length > 0 && !tooLong && !disabled && !streaming;

  function submit() {
    if (!canSend) return;
    onSend(trimmed);
    setValue("");
    // Keep the caret in the box: most people send several messages in a row.
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // An IME composition ends on Enter too; sending there would eat the word.
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  }

  return (
    <div className={cn("border-t border-line bg-paper/95 backdrop-blur-md", className)}>
      <div className="mx-auto w-full max-w-3xl px-4 py-3 sm:px-6">
        {notice ? <div className="mb-2.5">{notice}</div> : null}

        <div
          className={cn(
            "flex items-end gap-2 rounded-lg border border-line-strong bg-surface p-2",
            "shadow-soft transition-colors focus-within:border-focus",
            tooLong && "border-danger",
          )}
        >
          <Textarea
            ref={inputRef}
            autoResize
            rows={1}
            maxRows={12}
            value={value}
            disabled={disabled}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            aria-label="Message"
            aria-describedby={value.length >= COUNTER_FROM ? countId : undefined}
            aria-invalid={tooLong || undefined}
            className={cn(
              "min-h-0 flex-1 resize-none border-0 bg-transparent px-2 py-1.5 shadow-none",
              "focus-visible:outline-none focus-visible:border-0",
            )}
          />

          {streaming ? (
            <Button variant="secondary" size="sm" onClick={onStop} className="mb-0.5">
              <IconStop className="size-4" />
              Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              disabled={!canSend}
              aria-label="Send message"
              className="mb-0.5 aspect-square px-0"
            >
              <IconSend className="size-4" />
            </Button>
          )}
        </div>

        <div className="mt-1.5 flex items-center justify-between gap-3 px-1">
          <p className="text-xs text-ink-muted">
            <kbd className="font-mono text-2xs">Enter</kbd> sends ·{" "}
            <kbd className="font-mono text-2xs">Shift</kbd>+
            <kbd className="font-mono text-2xs">Enter</kbd> for a new line
          </p>
          {value.length >= COUNTER_FROM ? (
            <p
              id={countId}
              aria-live="polite"
              className={cn("font-mono text-2xs tabular-nums", tooLong ? "text-danger" : "text-ink-muted")}
            >
              {value.length.toLocaleString()} / {MAX_MESSAGE_LENGTH.toLocaleString()}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
