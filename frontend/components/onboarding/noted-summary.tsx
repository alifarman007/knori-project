"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { MEMORY_KIND_LABEL } from "@/lib/labels";
import type { OnboardingNote } from "@/lib/types";

export interface NotedSummaryProps {
  noted: readonly OnboardingNote[];
  onStart: () => void;
  starting?: boolean;
}

/**
 * "Here's what I noted" — the first time the person sees the whole promise.
 *
 * Every line is a statement KnoRI will reason with, shown next to the words it
 * came from. If the quote does not support the statement, that is visible
 * immediately, on the first screen, before any trust has been asked for.
 */
export function NotedSummary({ noted, onStart, starting = false }: NotedSummaryProps) {
  return (
    <div>
      <h1 className="text-2xl">Here is what I noted</h1>
      <p className="mt-2 max-w-prose text-base text-ink-muted">
        {noted.length > 0
          ? "Each of these is something KnoRI will remember, with your own words underneath it. All of it is editable on your memory page."
          : "Nothing firm enough to keep yet — that is fine. It fills in as you talk."}
      </p>

      {noted.length > 0 ? (
        <ul className="mt-8 flex flex-col">
          {noted.map((note) => (
            <li key={note.id} className="border-b border-line py-5 first:pt-0 last:border-0">
              <p className="knori-eyebrow">{MEMORY_KIND_LABEL[note.kind]}</p>
              <p className="mt-2 font-serif text-md leading-relaxed text-ink">{note.statement}</p>
              {note.quote_text ? (
                <blockquote className="mt-2.5 border-l-2 border-accent-line pl-3 text-base leading-relaxed text-ink-secondary">
                  &ldquo;{note.quote_text}&rdquo;
                </blockquote>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-9 border-t border-line pt-6">
        <p className="max-w-prose knori-prose text-base">
          From here it is just a conversation. KnoRI will not tell you it has noticed a pattern
          until the same thing shows up on at least two different days — so the first card usually
          arrives a day or two in, not tonight.
        </p>
        <Button
          size="lg"
          className="mt-6"
          loading={starting}
          loadingText="Opening…"
          onClick={onStart}
        >
          Start talking
        </Button>
      </div>
    </div>
  );
}
