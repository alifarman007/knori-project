"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import { useModalBehaviour, useMounted } from "@/components/ui/use-modal";
import { cn } from "@/lib/utils";

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Which edge it comes from on desktop. On phones it is always the bottom. */
  side?: "right" | "left";
  className?: string;
}

/**
 * A bottom sheet on phones, a side panel from 640px up. Correcting a
 * Recognition happens here, so it has to be comfortable to type in on a phone:
 * the grab handle and the rounded top edge are for thumbs, not decoration.
 */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  side = "right",
  className,
}: SheetProps) {
  const panelRef = useModalBehaviour({ open, onClose });
  const mounted = useMounted();
  const reactId = React.useId();
  const id = `sh${reactId.replace(/:/g, "")}`;

  if (!mounted || !open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-overlay backdrop-blur-[2px] animate-fade"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={description ? `${id}-desc` : undefined}
        tabIndex={-1}
        className={cn(
          "absolute inset-x-0 bottom-0 flex max-h-[88vh] flex-col rounded-t-xl border border-line",
          "bg-raised shadow-float focus:outline-none",
          "motion-safe:animate-[sheet-up_0.3s_var(--ease-out-quiet)_both]",
          "sm:inset-y-0 sm:max-h-none sm:w-full sm:max-w-md sm:rounded-none",
          side === "right"
            ? "sm:left-auto sm:right-0 sm:rounded-l-xl sm:border-r-0 motion-safe:sm:animate-[sheet-right_0.3s_var(--ease-out-quiet)_both]"
            : "sm:right-auto sm:left-0 sm:rounded-r-xl sm:border-l-0 motion-safe:sm:animate-[sheet-left_0.3s_var(--ease-out-quiet)_both]",
          className,
        )}
      >
        <span
          aria-hidden="true"
          className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-line-strong sm:hidden"
        />

        <div className="flex items-start justify-between gap-4 px-5 pb-4 pt-4 sm:px-6 sm:pt-6">
          <div className="min-w-0">
            <h2 id={`${id}-title`} className="font-serif text-xl text-ink">
              {title}
            </h2>
            {description ? (
              <p id={`${id}-desc`} className="mt-1.5 text-base text-ink-muted">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className={cn(
              "-mr-1 grid size-8 shrink-0 place-items-center rounded-sm text-ink-muted",
              "transition-colors hover:bg-sunken hover:text-ink",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
            )}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
              <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 sm:px-6">{children}</div>

        {footer ? (
          <div className="flex flex-col-reverse gap-2 border-t border-line px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
