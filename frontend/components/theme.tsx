"use client";

import * as React from "react";

import { IconMoon, IconSun } from "@/components/icons";
import { cn } from "@/lib/utils";

export type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "knori-theme";

/**
 * Runs before first paint so the page never flashes the wrong palette.
 * Kept as a string because it has to be inline in <head>, ahead of React.
 */
export const themeScript = `(function(){try{var t=localStorage.getItem("${STORAGE_KEY}");if(t==="dark"||t==="light"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})();`;

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** What is actually on screen right now. */
  resolved: "light" | "dark";
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = React.useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside <ThemeProvider>");
  return context;
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>("system");
  const [resolved, setResolved] = React.useState<"light" | "dark">("light");

  React.useEffect(() => {
    let stored: Theme = "system";
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      if (value === "dark" || value === "light") stored = value;
    } catch {
      // Private mode or blocked storage: the media query still works.
    }
    setThemeState(stored);
    setResolved(stored === "system" ? (systemPrefersDark() ? "dark" : "light") : stored);
  }, []);

  React.useEffect(() => {
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(media.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = React.useCallback((next: Theme) => {
    setThemeState(next);
    const root = document.documentElement;
    if (next === "system") {
      root.removeAttribute("data-theme");
      setResolved(systemPrefersDark() ? "dark" : "light");
    } else {
      root.setAttribute("data-theme", next);
      setResolved(next);
    }
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Nothing to do: the choice simply will not survive a reload.
    }
  }, []);

  const value = React.useMemo<ThemeContextValue>(
    () => ({ theme, setTheme, resolved }),
    [theme, setTheme, resolved],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function ThemeToggle({ className }: { className?: string }) {
  const { resolved, setTheme } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      className={cn(
        "grid size-9 place-items-center rounded-md border border-transparent text-ink-muted",
        "transition-colors hover:bg-sunken hover:text-ink",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        className,
      )}
    >
      {resolved === "dark" ? <IconSun className="size-[18px]" /> : <IconMoon className="size-[18px]" />}
    </button>
  );
}
