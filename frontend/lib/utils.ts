import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes so a caller's `className` always wins. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

let idCounter = 0;

/**
 * Stable-per-instance id for aria wiring.
 *
 * React's `useId` is the right tool inside components; this exists for the few
 * helpers that run outside a render (toasts, imperative dialogs).
 */
export function nextId(prefix = "knori"): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}
