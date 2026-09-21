import { cn } from "@/lib/utils";

export interface SpinnerProps {
  className?: string;
  /** Announced to screen readers. Pass null inside a button that already says it. */
  label?: string | null;
}

export function Spinner({ className, label = "Loading" }: SpinnerProps) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-live={label ? "polite" : undefined}
      className={cn("inline-flex items-center", className)}
    >
      <svg
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="size-4 animate-spin-quiet"
      >
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.22" strokeWidth="1.75" />
        <path
          d="M8 1.5A6.5 6.5 0 0 1 14.5 8"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}
