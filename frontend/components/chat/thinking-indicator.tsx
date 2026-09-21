import { cn } from "@/lib/utils";

export interface ThinkingIndicatorProps {
  className?: string;
  /** What it is doing, in case the wait is about something other than a reply. */
  label?: string;
}

/**
 * Three marks settling, in the accent.
 *
 * The global `prefers-reduced-motion` rule flattens the animation, so the dots
 * stay visible and simply stop moving rather than disappearing.
 */
export function ThinkingIndicator({ className, label = "KnoRI is thinking" }: ThinkingIndicatorProps) {
  return (
    <p
      role="status"
      aria-live="polite"
      className={cn("flex items-center gap-2 text-sm text-ink-muted", className)}
    >
      <span aria-hidden="true" className="flex items-end gap-[3px]">
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className="size-1.5 rounded-full bg-accent motion-safe:animate-[fade_1.1s_ease-in-out_infinite_alternate]"
            style={{ animationDelay: `${index * 180}ms` }}
          />
        ))}
      </span>
      <span>{label}</span>
    </p>
  );
}
