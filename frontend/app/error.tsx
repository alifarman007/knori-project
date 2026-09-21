"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/wordmark";

/**
 * The last line of defence. It shows the digest Next attaches to the error so a
 * person can quote one string and have it found in the server logs.
 */
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="relative z-10 flex min-h-dvh flex-col items-center justify-center px-4 text-center">
      <Wordmark size="sm" />
      <p className="knori-eyebrow mt-10">Something broke</p>
      <h1 className="mt-4 text-3xl">That did not load</h1>
      <p className="knori-prose mt-4 max-w-md">
        Nothing you said was lost. Try again, and if it keeps happening send us the reference below.
      </p>
      {error.digest ? (
        <p className="mt-4 font-mono text-2xs text-ink-muted">reference {error.digest}</p>
      ) : null}
      <Button className="mt-8" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
