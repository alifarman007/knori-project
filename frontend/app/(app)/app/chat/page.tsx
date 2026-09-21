import type { Metadata } from "next";
import * as React from "react";

import { ChatScreen } from "@/components/chat/chat-screen";

export const metadata: Metadata = { title: "Chat" };

export default function ChatIndexPage() {
  return (
    <React.Suspense fallback={null}>
      <ChatScreen conversationId={null} />
    </React.Suspense>
  );
}
