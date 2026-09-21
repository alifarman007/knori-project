"use client";

import * as React from "react";

import { useToast } from "@/components/ui/toast";
import { ApiError, errorMessage } from "@/lib/api";

export type ReportError = (error: unknown, title?: string) => void;

/**
 * One way to show a failure.
 *
 * Every error toast carries the request id when the API sent one, and stays on
 * screen until it is dismissed, because a five-second toast with a reference
 * number in it is a reference number nobody can write down.
 */
export function useErrorToast(): ReportError {
  const { toast } = useToast();

  return React.useCallback(
    (error: unknown, title?: string) => {
      const apiError = error instanceof ApiError ? error : null;
      const description = apiError?.requestId
        ? `${errorMessage(error)} · reference ${apiError.requestId}`
        : errorMessage(error);

      toast({
        title: title ?? apiError?.title ?? "That did not work",
        description,
        tone: "danger",
        duration: 0,
      });
    },
    [toast],
  );
}
