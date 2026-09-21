import type { Metadata } from "next";

import { LegalPage } from "@/components/marketing/legal-page";

export const metadata: Metadata = {
  title: "Terms of service (draft-0)",
  description: "The working draft of KnoRI's terms of service. Not yet reviewed by a lawyer.",
  robots: { index: false, follow: false },
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of service"
      version="draft-0"
      updated="21 September 2026"
      intro="These terms describe what KnoRI does, what you can expect from it, and what we ask of you while using it. They are written in plain English on purpose; where a sentence is ambiguous, read it the way a reasonable person would."
      sections={[
        {
          heading: "What KnoRI is",
          paragraphs: [
            "KnoRI is a chat product that remembers what you tell it and, when enough of what you have said points the same way, shows you a Recognition: a pattern it noticed, together with the exact words behind it.",
            "KnoRI is not a medical, psychological, legal or financial service. Nothing it says is advice, diagnosis or treatment, and it must not be used as a substitute for a professional.",
          ],
        },
        {
          heading: "Your account",
          paragraphs: [
            "During the beta, an account requires an invite code. You are responsible for keeping your password and your invite code to yourself, and for everything done through your account.",
            "You must be at least 18 years old to use KnoRI, and you must give an email address you actually control so account recovery works.",
          ],
        },
        {
          heading: "What you may not do",
          paragraphs: [
            "Do not use KnoRI to break the law, to harass anyone, or to store information about other people that they have not agreed to you sharing.",
            "Do not attempt to extract the prompts, model outputs or engine internals for the purpose of rebuilding them elsewhere, and do not automate access to the service without asking us first.",
          ],
        },
        {
          heading: "Recognitions and corrections",
          paragraphs: [
            "Recognitions are produced by software and can be wrong. That is why every card can be accepted, corrected, rejected or set aside, and why every card shows the evidence it rests on.",
            "When you correct a Recognition, your correction is stored and used in future reasoning. We do not guarantee that a correction erases every trace of the original claim from the record; it does guarantee that the claim will not be proposed to you again while the correction stands.",
          ],
        },
        {
          heading: "Availability and change",
          paragraphs: [
            "KnoRI is in beta. Features may change, and the service may be unavailable while we deploy or repair it. We will tell you before we remove something you rely on.",
            "We may update these terms. If a change matters, you will be asked to accept the new version before you carry on, and the version you accepted is recorded.",
          ],
        },
        {
          heading: "Ending it",
          paragraphs: [
            "You can delete your account at any time from Settings. After one day of grace, every row belonging to you is removed from the live database; backups age out within thirty days.",
            "We may close an account that breaks these terms, and we will say why unless the law prevents it.",
          ],
        },
        {
          heading: "Liability",
          paragraphs: [
            "To the extent the law allows, KnoRI is provided as it is, and we are not liable for indirect or consequential loss arising from your use of it.",
            "Nothing in these terms limits liability that cannot be limited by law.",
          ],
        },
      ]}
    />
  );
}
