import type { Metadata } from "next";
import * as React from "react";

import { ChatScreen } from "@/components/chat/chat-screen";

export const metadata: Metadata = { title: "Chat" };

export default async function ChatConversationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    // `useSearchParams` reads the `?m=&hl=` deep link inside the thread.
    <React.Suspense fallback={null}>
      <ChatScreen conversationId={id} />
    </React.Suspense>
  );
}
