import type { Metadata } from "next";

import { OnboardingScreen } from "@/components/onboarding/onboarding-screen";

export const metadata: Metadata = {
  title: "Getting started",
  robots: { index: false, follow: false },
};

export default function OnboardingPage() {
  return <OnboardingScreen />;
}
