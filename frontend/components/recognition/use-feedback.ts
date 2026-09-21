"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { useToast } from "@/components/ui/toast";
import { recognitions as api } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import { useErrorToast } from "@/lib/use-error-toast";
import type {
  FeedbackAction,
  Page,
  ReasonCode,
  Recognition,
  RecognitionDetail,
  RecognitionState,
  Uuid,
} from "@/lib/types";

export interface FeedbackInput {
  id: Uuid;
  action: FeedbackAction;
  correction_text?: string;
  reason_code?: ReasonCode;
}

/** What the card looks like the instant the person answers. */
const NEXT_STATE: Record<FeedbackAction, RecognitionState> = {
  accept: "accepted",
  correct: "corrected",
  reject: "rejected",
  dismiss: "dismissed",
};

const ACKNOWLEDGEMENT: Record<FeedbackAction, string> = {
  accept: "Noted — KnoRI will treat this as settled.",
  correct: "Your correction is in. KnoRI is working out what it changes.",
  reject: "Noted — this claim will not come back.",
  dismiss: "Set aside for now.",
};

export interface UseFeedbackOptions {
  /** Called with the feedback id so a screen can watch for the effect. */
  onQueued?: (feedbackId: Uuid, input: FeedbackInput) => void;
  /** Suppress the toast where the screen says it better itself. */
  quiet?: boolean;
}

/**
 * Accept · Correct · Reject · Dismiss, applied optimistically.
 *
 * `POST /recognitions/{id}/feedback` returns 202: the real work (assertions,
 * rescoring, a revised card) happens in a job and arrives later over SSE. The
 * card therefore has to settle immediately — waiting for the job would leave
 * four buttons spinning for seconds after the person has already decided.
 */
export function useFeedback(options: UseFeedbackOptions = {}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const reportError = useErrorToast();
  const [pending, setPending] = React.useState<{ id: Uuid; action: FeedbackAction } | null>(null);

  const optionsRef = React.useRef(options);
  optionsRef.current = options;

  const mutation = useMutation({
    mutationFn: (input: FeedbackInput) =>
      api.feedback(input.id, {
        action: input.action,
        ...(input.correction_text ? { correction_text: input.correction_text } : {}),
        ...(input.reason_code ? { reason_code: input.reason_code } : {}),
      }),

    onMutate: (input) => {
      setPending({ id: input.id, action: input.action });
      const state = NEXT_STATE[input.action];
      const resolvedAt = new Date().toISOString();

      queryClient.setQueryData<RecognitionDetail>(keys.recognition(input.id), (current) =>
        current ? { ...current, state, resolved_at: resolvedAt } : current,
      );
      queryClient.setQueriesData<Page<Recognition>>({ queryKey: ["recognitions"] }, (current) => {
        if (!current?.items) return current;
        return {
          ...current,
          items: current.items.map((item) =>
            item.id === input.id ? { ...item, state, resolved_at: resolvedAt } : item,
          ),
        };
      });
    },

    onSuccess: (result, input) => {
      if (!optionsRef.current.quiet) {
        toast({
          title: ACKNOWLEDGEMENT[input.action],
          tone: input.action === "accept" ? "positive" : "accent",
        });
      }
      if (result?.feedback_id) optionsRef.current.onQueued?.(result.feedback_id, input);
    },

    onError: (error) => reportError(error, "That answer did not save"),

    onSettled: (_result, _error, input) => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: keys.recognition(input.id) });
      void queryClient.invalidateQueries({ queryKey: ["recognitions"] });
      void queryClient.invalidateQueries({ queryKey: keys.recognitionSummary });
    },
  });

  return {
    submit: mutation.mutate,
    submitAsync: mutation.mutateAsync,
    pending,
    /** The action in flight for one card, for the spinner on that button only. */
    pendingFor: (id: Uuid): FeedbackAction | null => (pending?.id === id ? pending.action : null),
    isPending: mutation.isPending,
  };
}
