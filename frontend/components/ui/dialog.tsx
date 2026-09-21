"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import { useModalBehaviour, useMounted } from "@/components/ui/use-modal";
import { cn } from "@/lib/utils";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  /** Buttons; laid out right on desktop, stacked full-width on phones. */
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  dismissible?: boolean;
  className?: string;
}

const SIZES = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" } as const;

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  dismissible = true,
  className,
}: DialogProps) {
  const panelRef = useModalBehaviour({ open, onClose, dismissible });
  const mounted = useMounted();
  const reactId = React.useId();
  const id = `d${reactId.replace(/:/g, "")}`;

  if (!mounted || !open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <div
        aria-hidden="true"
        onClick={dismissible ? onClose : undefined}
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
          "relative w-full rounded-lg border border-line bg-raised shadow-float",
          "animate-rise focus:outline-none",
          SIZES[size],
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5 sm:px-6 sm:pt-6">
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
          {dismissible ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className={cn(
                "-mr-1 -mt-1 grid size-8 shrink-0 place-items-center rounded-sm text-ink-muted",
                "transition-colors hover:bg-sunken hover:text-ink",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
              )}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4">
                <path
                  d="m4 4 8 8M12 4l-8 8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          ) : null}
        </div>

        {children ? (
          <div className="max-h-[60vh] overflow-y-auto px-5 py-4 sm:px-6 sm:py-5">{children}</div>
        ) : (
          <div className="h-2" />
        )}

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
