import { AppGate } from "@/components/shell/app-gate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppGate>{children}</AppGate>;
}
