import type { Metadata } from "next";

import { LegalPage } from "@/components/marketing/legal-page";

export const metadata: Metadata = {
  title: "Privacy (draft-0)",
  description: "The working draft of KnoRI's privacy note. Not yet reviewed by a lawyer.",
  robots: { index: false, follow: false },
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy"
      version="draft-0"
      updated="21 September 2026"
      intro="KnoRI only works if you are willing to say true things to it. This note describes exactly what is kept, what is worked out from it, who else sees it, and how to take it all back."
      sections={[
        {
          heading: "What we keep",
          paragraphs: [
            "Your account details: email address, display name, the name you want to be called, your timezone, and a hash of your password. We never store the password itself.",
            "Your conversations: every message you send and every reply, with the time it happened.",
            "Observations drawn from your messages: a short neutral restatement, the exact quote it came from, and where that quote sits in your message.",
            "Memory: the list of things you told KnoRI, which you can read, edit, pin or retract at any time.",
            "Recognitions: the cards KnoRI showed you, the evidence frozen at the moment each was written, what you did about it, and every correction you made.",
          ],
        },
        {
          heading: "What we work out",
          paragraphs: [
            "KnoRI infers four kinds of thing and no others: patterns, preferences, values and tensions. Each one needs at least two things you said, on at least two different calendar days, at least twelve hours apart.",
            "KnoRI does not infer anything about health, mental health, sexual orientation, religion, ethnicity, immigration status, criminal matters, politics or financial distress. If you mention one of these, it is stored as your words and is never used as evidence for a Recognition.",
            "KnoRI holds no records about other people. When you talk about someone else, your sentence is kept as your sentence; no profile of that person is created.",
          ],
        },
        {
          heading: "Who else sees it",
          paragraphs: [
            "Your messages are sent to our model providers — Anthropic and OpenAI — so they can produce your replies and your Recognitions. They act as processors and do not use your content to train their models.",
            "Nobody at KnoRI reads your conversations as a matter of routine. Administrative access exists for debugging and is written to an audit log.",
            "We do not sell your data, and there is no advertising in KnoRI.",
          ],
        },
        {
          heading: "Deleting things",
          paragraphs: [
            "Delete a message and the quotes taken from it are scrubbed in the same transaction — the record that evidence existed stays, the words do not. A Recognition that drops below two pieces of supporting evidence is withdrawn.",
            "Retract a memory or a correction and it stops being used in reasoning from that moment.",
            "Delete your account and everything belonging to you is removed after one day of grace, so a mistake can be undone. Encrypted backups age out within thirty days.",
          ],
        },
        {
          heading: "Taking it with you",
          paragraphs: [
            "Settings has an export button. It produces one JSON file containing your conversations, messages, memory, Recognitions with their evidence and feedback, and your corrections.",
          ],
        },
        {
          heading: "Security",
          paragraphs: [
            "Passwords are hashed with argon2id. Sessions are opaque tokens in a cookie that JavaScript cannot read, and they are rotated when you sign in.",
            "Every query is scoped to your account, and a request for somebody else's row is answered as if it does not exist.",
          ],
        },
        {
          heading: "Asking us",
          paragraphs: [
            "Write to privacy@knori.app with any question about your data, including a request for a copy or for deletion. We answer within thirty days.",
          ],
        },
      ]}
    />
  );
}
