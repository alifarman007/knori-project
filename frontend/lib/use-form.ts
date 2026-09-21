"use client";

import * as React from "react";

import { ApiError, errorMessage } from "@/lib/api";

export type FieldErrors<T> = Partial<Record<keyof T & string, string>>;
/** What a `validate` function returns: undefined simply means "this one is fine". */
export type ValidationResult<T> = Partial<Record<keyof T & string, string | undefined>>;

/** Drop the undefined entries so `Object.keys` counts only real problems. */
function prune<T>(result: ValidationResult<T>): FieldErrors<T> {
  const errors: FieldErrors<T> = {};
  for (const [key, value] of Object.entries(result)) {
    if (typeof value === "string" && value) errors[key as keyof T & string] = value;
  }
  return errors;
}

export interface FormState<T extends Record<string, string>> {
  values: T;
  errors: FieldErrors<T>;
  /** Whatever the server said when it rejected the whole form. */
  formError: string | null;
  requestId: string | null;
  submitting: boolean;
  submitted: boolean;
  setValue: (name: keyof T & string, value: string) => void;
  /** Validates on blur, so nobody is corrected while still typing. */
  blur: (name: keyof T & string) => void;
  handleSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  reset: () => void;
}

export interface UseFormOptions<T extends Record<string, string>> {
  initial: T;
  validate: (values: T) => ValidationResult<T>;
  onSubmit: (values: T) => Promise<void> | void;
}

/**
 * Small controlled-form helper: local rules on blur and on submit, then the
 * server's field errors merged in when a request comes back 4xx.
 */
export function useForm<T extends Record<string, string>>({
  initial,
  validate,
  onSubmit,
}: UseFormOptions<T>): FormState<T> {
  const [values, setValues] = React.useState<T>(initial);
  const [errors, setErrors] = React.useState<FieldErrors<T>>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [requestId, setRequestId] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);

  // Read by `blur`, which must not put a side effect inside a state updater:
  // React invokes updaters twice in development.
  const valuesRef = React.useRef(values);
  valuesRef.current = values;

  const setValue = React.useCallback((name: keyof T & string, value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    setErrors((current) => {
      if (!(name in current)) return current;
      const next = { ...current };
      delete next[name];
      return next;
    });
  }, []);

  const blur = React.useCallback(
    (name: keyof T & string) => {
      const message = prune(validate(valuesRef.current))[name];
      setErrors((previous) => (message ? { ...previous, [name]: message } : stripKey(previous, name)));
    },
    [validate],
  );

  const handleSubmit = React.useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const form = event.currentTarget;
      setFormError(null);
      setRequestId(null);

      const found = prune(validate(values));
      setErrors(found);
      if (Object.keys(found).length > 0) {
        // After the re-render, so aria-invalid is actually on the element.
        window.setTimeout(() => focusFirstInvalid(form), 0);
        return;
      }

      setSubmitting(true);
      void Promise.resolve(onSubmit(values))
        .then(() => setSubmitted(true))
        .catch((error: unknown) => {
          if (error instanceof ApiError) {
            const fields: FieldErrors<T> = {};
            for (const [key, messages] of Object.entries(error.fieldErrors)) {
              if (key in values && messages[0]) {
                fields[key as keyof T & string] = messages[0];
              }
            }
            setErrors(fields);
            setRequestId(error.requestId ?? null);
            setFormError(Object.keys(fields).length > 0 ? null : (error.detail ?? error.title));
          } else {
            setFormError(errorMessage(error));
          }
        })
        .finally(() => setSubmitting(false));
    },
    [values, validate, onSubmit],
  );

  const reset = React.useCallback(() => {
    setValues(initial);
    setErrors({});
    setFormError(null);
    setSubmitted(false);
  }, [initial]);

  return {
    values,
    errors,
    formError,
    requestId,
    submitting,
    submitted,
    setValue,
    blur,
    handleSubmit,
    reset,
  };
}

function stripKey<T>(errors: FieldErrors<T>, name: keyof T & string): FieldErrors<T> {
  if (!(name in errors)) return errors;
  const next = { ...errors };
  delete next[name];
  return next;
}

function focusFirstInvalid(form: HTMLFormElement): void {
  const invalid = form.querySelector<HTMLElement>("[aria-invalid='true']");
  invalid?.focus();
}
