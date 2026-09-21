import { cn } from "@/lib/utils";

export interface SkeletonProps {
  className?: string;
}

/**
 * A placeholder block. The sweep is a background animation, so the global
 * prefers-reduced-motion rule turns it into a flat tint without extra code.
 */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden rounded-sm bg-sunken",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-[sweep_1.6s_infinite]",
        "after:bg-gradient-to-r after:from-transparent after:via-white/45 after:to-transparent",
        "dark:after:via-white/6",
        className,
      )}
    />
  );
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3.5", index === lines - 1 ? "w-3/5" : "w-full")}
        />
      ))}
    </div>
  );
}
