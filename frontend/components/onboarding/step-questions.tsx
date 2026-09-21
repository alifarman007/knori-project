"use client";

import * as React from "react";

import { validateAnswer } from "@/components/onboarding/questions";
import { ThinkingIndicator } from "@/components/chat/thinking-indicator";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { onboarding } from "@/lib/endpoints";
import type { OnboardingNote, OnboardingQuestion } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";
import { cn } from "@/lib/utils";

interface Turn {
  role: "knori" | "you";
  text: string;
}

export interface StepQuestionsProps {
  questions: readonly OnboardingQuestion[];
  /** Answers already stored, so a reload does not start over. */
  answered: number;
  onFinished: (noted: OnboardingNote[]) => void;
}

/**
 * Step three: three questions, one at a time, as a conversation.
 *
 * It is deliberately not a form with three boxes. The first thing a person does
 * in KnoRI should be the thing they will keep doing — type a paragraph and get
 * a reply — and the answers are stored as real messages in an onboarding
 * conversation, which is what makes them quotable later.
 */
export function StepQuestions({ questions, answered, onFinished }: StepQuestionsProps) {
  const [index, setIndex] = React.useState(answered);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [text, setText] = React.useState("");
  const [error, setError] = React.useState<string | undefined>(undefined);
  const [busy, setBusy] = React.useState(false);
  const [noted, setNoted] = React.useState<OnboardingNote[]>([]);
  const reportError = useErrorToast();
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const endRef = React.useRef<HTMLDivElement | null>(null);

  const question = questions[index];
  const asked = React.useRef(-1);

  // Ask the next question once, after the previous answer has landed.
  React.useEffect(() => {
    if (!question || asked.current === index) return;
    asked.current = index;
    setTurns((current) => [...current, { role: "knori", text: question.prompt }]);
  }, [question, index]);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns.length, busy]);

  async function send() {
    if (!question) return;
    const problem = validateAnswer(text);
    setError(problem);
    if (problem) {
      inputRef.current?.focus();
      return;
    }

    const answer = text.trim();
    setTurns((current) => [...current, { role: "you", text: answer }]);
    setText("");
    setBusy(true);

    try {
      const result = await onboarding.answer(question.index, answer);
      const captured = [...noted, ...(result.noted ?? [])];
      setNoted(captured);
      if (result.reply) {
        setTurns((current) => [...current, { role: "knori", text: result.reply as string }]);
      }
      const next = index + 1;
      if (next >= questions.length) {
        onFinished(captured);
        return;
      }
      setIndex(next);
    } catch (cause) {
      reportError(cause, "That answer did not save");
      // Put their words back in the box rather than losing them.
      setTurns((current) => current.slice(0, -1));
      setText(answer);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="knori-eyebrow">
        Question {Math.min(index + 1, questions.length)} of {questions.length}
      </p>

      <div className="mt-6 flex flex-col gap-6" aria-live="polite">
        {turns.map((turn, turnIndex) => (
          <div
            key={`${turn.role}-${turnIndex}`}
            className={cn(turn.role === "you" && "flex justify-end")}
          >
            {turn.role === "knori" ? (
              <p className="knori-prose max-w-prose text-ink">{turn.text}</p>
            ) : (
              <p className="max-w-[min(38rem,88%)] whitespace-pre-wrap rounded-lg rounded-br-sm border border-line bg-sunken px-4 py-3 text-base leading-relaxed text-ink">
                {turn.text}
              </p>
            )}
          </div>
        ))}
        {busy ? <ThinkingIndicator /> : null}
        <div ref={endRef} />
      </div>

      {question?.note && !busy ? (
        <p className="mt-3 text-sm text-ink-muted">{question.note}</p>
      ) : null}

      <div className="mt-6">
        <label htmlFor="onboarding-answer" className="sr-only">
          Your answer
        </label>
        <Textarea
          id="onboarding-answer"
          ref={inputRef}
          autoResize
          rows={3}
          maxRows={10}
          value={text}
          disabled={busy}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "onboarding-answer-error" : undefined}
          onChange={(event) => {
            setText(event.target.value);
            if (error) setError(undefined);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            void send();
          }}
          placeholder="Take as long as you like."
        />
        {error ? (
          <p id="onboarding-answer-error" role="alert" className="mt-1.5 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <div className="mt-3 flex items-center gap-3">
          <Button size="lg" loading={busy} onClick={() => void send()}>
            {index + 1 >= questions.length ? "Finish" : "Send"}
          </Button>
          <span className="text-xs text-ink-muted">
            <kbd className="font-mono text-2xs">Enter</kbd> sends
          </span>
        </div>
      </div>
    </div>
  );
}
