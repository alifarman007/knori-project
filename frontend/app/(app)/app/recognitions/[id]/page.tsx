import type { Metadata } from "next";

import { InspectScreen } from "@/components/recognition/inspect-screen";

export const metadata: Metadata = { title: "Recognition" };

export default async function RecognitionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <InspectScreen recognitionId={id} />;
}
