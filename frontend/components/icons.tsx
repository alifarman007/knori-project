import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * A small line-drawn set, all on a 20-unit grid with a 1.6 stroke, so they sit
 * on the same optical weight as the text. No emoji anywhere in this product:
 * an emoji is somebody else's drawing with somebody else's tone.
 */

export type IconProps = React.SVGProps<SVGSVGElement>;

function Icon({ className, children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={cn("size-5", className)}
      {...props}
    >
      {children}
    </svg>
  );
}

export function IconChat(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 6.2A2.2 2.2 0 0 1 5.7 4h8.6a2.2 2.2 0 0 1 2.2 2.2v5.1a2.2 2.2 0 0 1-2.2 2.2H8.6L5 16.4v-2.9h-.1a1.6 1.6 0 0 1-1.4-1.6z" />
    </Icon>
  );
}

/** The wordmark motif: a line of text with the marked rule beneath it. */
export function IconRecognition(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.2 5.4h11.6M4.2 8.8h7.4M4.2 12.2h9.2" />
      <path d="M4 16h8.4" strokeWidth="2.4" />
    </Icon>
  );
}

export function IconMemory(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 5.1c0-.8.7-1.4 1.5-1.3 1.6.2 3.3.7 4.5 1.6 1.2-.9 2.9-1.4 4.5-1.6.8-.1 1.5.5 1.5 1.3v8.3c0 .7-.6 1.3-1.3 1.3-1.5.1-3.2.6-4.7 1.6-1.5-1-3.2-1.5-4.7-1.6A1.3 1.3 0 0 1 4 13.4z" />
      <path d="M10 5.4V16" />
    </Icon>
  );
}

export function IconSettings(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 6.2h5.2M11.8 6.2h4.7M3.5 13.8h2.7M9.3 13.8h7.2" />
      <circle cx="10.2" cy="6.2" r="1.7" />
      <circle cx="7.7" cy="13.8" r="1.7" />
    </Icon>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m4.6 10.3 3.3 3.3 7.5-7.6" />
    </Icon>
  );
}

export function IconClose(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m5 5 10 10M15 5 5 15" />
    </Icon>
  );
}

export function IconPencil(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M13.4 3.9a1.6 1.6 0 0 1 2.3 0l.4.4a1.6 1.6 0 0 1 0 2.3l-8.3 8.3-3.3 1 1-3.3z" />
      <path d="M12.2 5.2 14.8 7.8" />
    </Icon>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 10h12M11.2 5.4 15.8 10l-4.6 4.6" />
    </Icon>
  );
}

export function IconQuote(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.5 12.5V9a3 3 0 0 1 3-3M11.5 12.5V9a3 3 0 0 1 3-3" />
      <path d="M4.5 12.5h3V9h-3zM11.5 12.5h3V9h-3z" />
    </Icon>
  );
}

export function IconCalendar(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.4" y="4.6" width="13.2" height="11.6" rx="1.6" />
      <path d="M3.4 8.3h13.2M7 3.2v2.6M13 3.2v2.6" />
    </Icon>
  );
}

export function IconShield(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3.2 15.6 5.3v4.1c0 3.2-2.2 6.1-5.6 7.4-3.4-1.3-5.6-4.2-5.6-7.4V5.3z" />
      <path d="m7.6 9.8 1.8 1.8 3.2-3.5" />
    </Icon>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15.6 12.4A6.2 6.2 0 0 1 7.6 4.4a6.4 6.4 0 1 0 8 8z" />
    </Icon>
  );
}

export function IconSun(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="3.4" />
      <path d="M10 2.6v1.8M10 15.6v1.8M17.4 10h-1.8M4.4 10H2.6M15.2 4.8l-1.3 1.3M6.1 13.9l-1.3 1.3M15.2 15.2l-1.3-1.3M6.1 6.1 4.8 4.8" />
    </Icon>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 5.5h13M3.5 10h13M3.5 14.5h13" />
    </Icon>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m5.5 8 4.5 4.5L14.5 8" />
    </Icon>
  );
}

export function IconExternal(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M11.4 4.2h4.4v4.4M15.4 4.6 9.2 10.8" />
      <path d="M14.6 11.6v3.2a1.6 1.6 0 0 1-1.6 1.6H5.2a1.6 1.6 0 0 1-1.6-1.6V7a1.6 1.6 0 0 1 1.6-1.6h3.2" />
    </Icon>
  );
}

export function IconScales(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 4v12M5.6 16h8.8M4.2 7.4h11.6M4.2 7.4 2 12h4.4zM15.8 7.4 13.6 12H18z" />
      <circle cx="10" cy="4" r="1" />
    </Icon>
  );
}

export function IconSpark(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3.2 11.5 8 16.4 9.5 11.5 11 10 16 8.5 11 3.6 9.5 8.5 8z" />
    </Icon>
  );
}

export function IconInbox(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.6 11.4 5.4 5a1.6 1.6 0 0 1 1.6-1.2h6a1.6 1.6 0 0 1 1.6 1.2l1.8 6.4v3.4a1.6 1.6 0 0 1-1.6 1.6H5.2a1.6 1.6 0 0 1-1.6-1.6z" />
      <path d="M3.6 11.4h3.2l.9 1.8h4.6l.9-1.8h3.2" />
    </Icon>
  );
}

/* ------------------------------------------------------------------ app */

export function IconSend(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.4 10 16.6 4.2l-2.5 12.4-4-4.2z" />
      <path d="m10.1 12.4 6.5-8.2" />
    </Icon>
  );
}

export function IconStop(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="5.4" y="5.4" width="9.2" height="9.2" rx="1.4" />
    </Icon>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 4.4v11.2M4.4 10h11.2" />
    </Icon>
  );
}

export function IconPin(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M12.4 3.2 16.8 7.6l-2.3.8-3.4 3.4-.3 3.1-4.3-4.3-4.3-4.3 3.1-.3L8.7 2.6z" />
      <path d="M6.5 13.5 3.4 16.6" />
    </Icon>
  );
}

export function IconTrash(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4.2 5.8h11.6M8.2 5.8V4.2h3.6v1.6M5.6 5.8l.7 9.2a1.3 1.3 0 0 0 1.3 1.2h4.8a1.3 1.3 0 0 0 1.3-1.2l.7-9.2" />
    </Icon>
  );
}

/** A mask, not an eye: incognito is about not being recorded, not about seeing. */
export function IconIncognito(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.2 10.4h13.6M6 10.4 7.1 6.1a1.3 1.3 0 0 1 1.3-1h3.2a1.3 1.3 0 0 1 1.3 1l1.1 4.3" />
      <circle cx="6.6" cy="13" r="2.2" />
      <circle cx="13.4" cy="13" r="2.2" />
      <path d="M8.8 12.8a2 2 0 0 1 2.4 0" />
    </Icon>
  );
}

export function IconHistory(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.6 10a6.4 6.4 0 1 0 1.9-4.5" />
      <path d="M3.4 3.6v3.2h3.2M10 6.4V10l2.4 1.6" />
    </Icon>
  );
}

export function IconArrowLeft(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M16 10H4M8.8 5.4 4.2 10l4.6 4.6" />
    </Icon>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M10 3.4v8.4M6.4 8.6 10 12.2l3.6-3.6" />
      <path d="M3.8 13.4v1.6a1.6 1.6 0 0 0 1.6 1.6h9.2a1.6 1.6 0 0 0 1.6-1.6v-1.6" />
    </Icon>
  );
}

export function IconRefresh(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M16.2 8.4A6.4 6.4 0 0 0 5.1 5.6M3.8 11.6a6.4 6.4 0 0 0 11.1 2.8" />
      <path d="M16.4 4.4v4h-4M3.6 15.6v-4h4" />
    </Icon>
  );
}

export function IconKey(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="7" cy="7" r="3.4" />
      <path d="m9.4 9.4 6 6M13.4 13.4l-1.4 1.4M15 15l-1.2 1.2" />
    </Icon>
  );
}
