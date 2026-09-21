"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import { useMounted } from "@/components/ui/use-modal";
import { cn } from "@/lib/utils";

export type ToastTone = "neutral" | "positive" | "danger" | "accent";

export interface ToastOptions {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Milliseconds. 0 keeps it until dismissed — use for errors with a request id. */
  duration?: number;
  action?: { label: string; onClick: () => void };
}

interface ToastRecord extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => number;
  dismiss: (id: number) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

/** `const { toast } = useToast()` — then `toast({ title: "Saved" })`. */
export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

const TONES: Record<ToastTone, string> = {
  neutral: "border-line",
  positive: "border-l-2 border-l-positive",
  danger: "border-l-2 border-l-danger",
  accent: "border-l-2 border-l-accent",
};

let nextToastId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastRecord[]>([]);
  const mounted = useMounted();
  const timers = React.useRef(new Map<number, number>());

  const dismiss = React.useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = React.useCallback(
    (options: ToastOptions) => {
      nextToastId += 1;
      const id = nextToastId;
      setToasts((current) => [...current.slice(-3), { ...options, id }]);
      const duration = options.duration ?? 5000;
      if (duration > 0) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  React.useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) window.clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const value = React.useMemo<ToastContextValue>(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {mounted
        ? createPortal(
            <div
              aria-live="polite"
              aria-relevant="additions"
              className={cn(
                "pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4",
                "sm:inset-x-auto sm:right-0 sm:items-end",
              )}
            >
              {toasts.map((item) => (
                <ToastItem key={item.id} record={item} onDismiss={() => dismiss(item.id)} />
              ))}
            </div>,
            document.body,
          )
        : null}
    </ToastContext.Provider>
  );
}

function ToastItem({ record, onDismiss }: { record: ToastRecord; onDismiss: () => void }) {
  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto w-full max-w-sm rounded-md border bg-raised px-4 py-3 shadow-float",
        "animate-rise",
        TONES[record.tone ?? "neutral"],
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-base font-medium text-ink">{record.title}</p>
          {record.description ? (
            <p className="mt-0.5 text-sm text-ink-muted">{record.description}</p>
          ) : null}
          {record.action ? (
            <button
              type="button"
              onClick={() => {
                record.action?.onClick();
                onDismiss();
              }}
              className="mt-2 text-sm font-medium text-accent underline underline-offset-4 hover:text-accent-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              {record.action.label}
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss notification"
          className="-mr-1 grid size-7 shrink-0 place-items-center rounded-sm text-ink-muted transition-colors hover:bg-sunken hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true" className="size-3.5">
            <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
