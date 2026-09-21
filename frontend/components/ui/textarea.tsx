"use client";

import * as React from "react";

import { useFieldContext } from "@/components/ui/field";
import { controlStyles } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Grow with the content up to `maxRows`, then scroll. */
  autoResize?: boolean;
  maxRows?: number;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    className,
    autoResize = false,
    maxRows = 12,
    rows = 4,
    id,
    onChange,
    "aria-describedby": describedBy,
    "aria-invalid": invalid,
    ...props
  },
  forwardedRef,
) {
  const field = useFieldContext();
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);

  const setRefs = React.useCallback(
    (node: HTMLTextAreaElement | null) => {
      innerRef.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    },
    [forwardedRef],
  );

  const resize = React.useCallback(() => {
    const node = innerRef.current;
    if (!node || !autoResize) return;
    node.style.height = "auto";
    const lineHeight = Number.parseFloat(getComputedStyle(node).lineHeight) || 24;
    const max = lineHeight * maxRows;
    node.style.height = `${Math.min(node.scrollHeight, max)}px`;
    node.style.overflowY = node.scrollHeight > max ? "auto" : "hidden";
  }, [autoResize, maxRows]);

  React.useEffect(resize, [resize, props.value]);

  return (
    <textarea
      ref={setRefs}
      id={id ?? field?.id}
      rows={rows}
      aria-describedby={describedBy ?? field?.describedBy}
      aria-invalid={invalid ?? (field?.invalid ? true : undefined)}
      onChange={(event) => {
        onChange?.(event);
        resize();
      }}
      className={cn(controlStyles, "resize-y leading-relaxed", autoResize && "resize-none", className)}
      {...props}
    />
  );
});
