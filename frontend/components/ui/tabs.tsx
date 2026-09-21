"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  baseId: string;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabs(component: string): TabsContextValue {
  const context = React.useContext(TabsContext);
  if (!context) throw new Error(`<${component}> must be used inside <Tabs>`);
  return context;
}

export interface TabsProps {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  children: React.ReactNode;
  className?: string;
}

export function Tabs({ value, defaultValue, onValueChange, children, className }: TabsProps) {
  const [internal, setInternal] = React.useState(defaultValue ?? "");
  const reactId = React.useId();
  const current = value ?? internal;

  const setValue = React.useCallback(
    (next: string) => {
      if (value === undefined) setInternal(next);
      onValueChange?.(next);
    },
    [value, onValueChange],
  );

  const context = React.useMemo<TabsContextValue>(
    () => ({ value: current, setValue, baseId: `t${reactId.replace(/:/g, "")}` }),
    [current, setValue, reactId],
  );

  return (
    <TabsContext.Provider value={context}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export interface TabsListProps {
  children: React.ReactNode;
  /** Required: a tablist without a name is unusable with a screen reader. */
  "aria-label": string;
  className?: string;
}

export function TabsList({ children, className, ...props }: TabsListProps) {
  const listRef = React.useRef<HTMLDivElement | null>(null);

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const tabs = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])') ?? [],
    );
    if (tabs.length === 0) return;
    const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
    event.preventDefault();

    let next: HTMLButtonElement | undefined;
    if (event.key === "Home") next = tabs[0];
    else if (event.key === "End") next = tabs[tabs.length - 1];
    else if (index !== -1) {
      const step = event.key === "ArrowRight" ? 1 : -1;
      next = tabs[(index + step + tabs.length) % tabs.length];
    } else next = tabs[0];

    next?.focus();
    next?.click();
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      onKeyDown={onKeyDown}
      className={cn(
        "flex gap-1 overflow-x-auto border-b border-line",
        "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export interface TabProps {
  value: string;
  children: React.ReactNode;
  /** Small count to the right of the label, e.g. how many are unread. */
  count?: number;
  disabled?: boolean;
  className?: string;
}

export function Tab({ value, children, count, disabled, className }: TabProps) {
  const { value: active, setValue, baseId } = useTabs("Tab");
  const selected = active === value;

  return (
    <button
      type="button"
      role="tab"
      id={`${baseId}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${baseId}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      disabled={disabled}
      onClick={() => setValue(value)}
      className={cn(
        "relative -mb-px flex shrink-0 items-center gap-2 whitespace-nowrap px-3 py-2.5 text-base",
        "border-b-2 transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus",
        selected
          ? "border-accent font-medium text-ink"
          : "border-transparent text-ink-muted hover:text-ink",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      {children}
      {count !== undefined && count > 0 ? (
        <span
          aria-hidden="true"
          className={cn(
            "rounded-full px-1.5 font-mono text-2xs leading-5 tabular-nums",
            selected ? "bg-accent-soft text-accent" : "bg-sunken text-ink-muted",
          )}
        >
          {count}
        </span>
      ) : null}
    </button>
  );
}

export interface TabPanelProps {
  value: string;
  children: React.ReactNode;
  className?: string;
}

export function TabPanel({ value, children, className }: TabPanelProps) {
  const { value: active, baseId } = useTabs("TabPanel");
  if (active !== value) return null;

  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${value}`}
      aria-labelledby={`${baseId}-tab-${value}`}
      tabIndex={0}
      className={cn("focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus", className)}
    >
      {children}
    </div>
  );
}
