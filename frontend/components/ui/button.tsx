import * as React from "react";

import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "accent";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  // Ink, not accent: the accent belongs to Recognition moments alone.
  primary:
    "bg-ink text-ink-inverted border border-ink hover:bg-ink/90 active:bg-ink shadow-soft " +
    "disabled:bg-ink/40 disabled:border-transparent",
  secondary:
    "bg-surface text-ink border border-line-strong hover:bg-sunken active:bg-sunken " +
    "shadow-soft disabled:text-ink-muted",
  ghost:
    "bg-transparent text-ink-secondary border border-transparent hover:bg-sunken hover:text-ink " +
    "active:bg-sunken disabled:text-ink-muted",
  danger:
    "bg-danger text-danger-ink border border-danger hover:bg-danger-hover active:bg-danger " +
    "shadow-soft disabled:opacity-50",
  accent:
    "bg-accent text-accent-ink border border-accent hover:bg-accent-hover active:bg-accent " +
    "shadow-soft disabled:opacity-50",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 gap-1.5 text-sm rounded-sm",
  md: "h-10 px-4 gap-2 text-base rounded-md",
  lg: "h-12 px-6 gap-2 text-md rounded-md",
};

export function buttonStyles(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  className?: string,
): string {
  return cn(
    "relative inline-flex items-center justify-center font-medium select-none",
    "transition-[background-color,border-color,color,box-shadow,transform] duration-150",
    "active:translate-y-px disabled:pointer-events-none disabled:active:translate-y-0",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
    "whitespace-nowrap",
    VARIANTS[variant],
    SIZES[size],
    className,
  );
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  /** Replaces the label while `loading`. Without it the label stays put. */
  loadingText?: string;
  fullWidth?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    loadingText,
    fullWidth = false,
    className,
    children,
    disabled,
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonStyles(variant, size, cn(fullWidth && "w-full", className))}
      {...props}
    >
      {loading ? (
        loadingText ? (
          <>
            <Spinner label={null} />
            <span>{loadingText}</span>
          </>
        ) : (
          <>
            {/* Keep the button the same width so the layout does not jump. */}
            <span className="invisible inline-flex items-center gap-2">{children}</span>
            <span className="absolute inset-0 grid place-items-center">
              <Spinner label={null} />
            </span>
            <span className="sr-only">Working…</span>
          </>
        )
      ) : (
        children
      )}
    </button>
  );
});
