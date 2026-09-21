import type { ComponentType } from "react";

import { IconChat, IconMemory, IconRecognition, IconSettings, type IconProps } from "@/components/icons";

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<IconProps>;
  /** Only Recognitions carries a count, and only when something is unread. */
  badge?: "recognitions";
}

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/app/chat", label: "Chat", icon: IconChat },
  { href: "/app/recognitions", label: "Recognitions", icon: IconRecognition, badge: "recognitions" },
  { href: "/app/memory", label: "Memory", icon: IconMemory },
  { href: "/app/settings", label: "Settings", icon: IconSettings },
];

/** `/app/recognitions/abc` should still light up the Recognitions item. */
export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
