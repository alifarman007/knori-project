"use client";

import * as React from "react";

import { useConnection } from "@/components/live/live-events";
import { cn } from "@/lib/utils";

/**
 * Shown only when the live channel has actually dropped, and only after a few
 * seconds — a deploy reconnects in under one, and a banner that flickers on
 * every restart teaches people to ignore banners.
 */
export function OfflineBanner({ className }: { className?: string }) {
  const connection = useConnection();
  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    if (connection !== "offline") {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), 4_000);
    return () => window.clearTimeout(timer);
  }, [connection]);

  if (!visible) return null;

  return (
    <div
      role="status"
      className={cn(
        "border-b border-line bg-sunken px-4 py-2 text-center text-sm text-ink-secondary",
        className,
      )}
    >
      <span aria-hidden="true" className="mr-2 inline-block size-1.5 rounded-full bg-ink-muted" />
      Not connected. Your messages still send — new Recognitions will appear once this comes back.
    </div>
  );
}
