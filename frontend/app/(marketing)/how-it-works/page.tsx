import type { Metadata } from "next";
import Link from "next/link";

import { Section, SectionHeading } from "@/components/marketing/section";
import { buttonStyles } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "The path from something you typed to a Recognition you can check, correct or throw away — and everything KnoRI refuses to do along the way.",
};

const LOOP = [
  {
    step: "Signal",
    title: "One thing you said",
    body: "A background pass reads your messages and pulls out single observations, each pinned to the exact characters you typed. If the quote cannot be found in your message letter for letter, the observation is dropped rather than stored.",
  },
  {
    step: "Evidence",
    title: "What each observation is doing",
    body: "Observations are attached to a candidate claim as supporting it, pulling against it, or giving context. Only things you said about yourself, in non-sensitive territory, are allowed to support anything.",
  },
  {
    step: "Interpretation",
    title: "A claim, not yet shown to you",
    body: "A model proposes a reading of the evidence: a pattern, a preference, a value, a tension. At this point nothing has been decided and you have not seen it.",
  },
  {
    step: "Confidence",
    title: "Arithmetic, not vibes",
    body: "A fixed formula weighs how much evidence there is, whether anything contradicts it, and how many separate days it spans. The model does not get to set its own score.",
  },
  {
    step: "Threshold",
    title: "Eleven checks, in order",
    body: "Ordinary code decides whether to show it. Two things on two days, twelve hours apart, no contradiction, nothing sensitive, nothing you already corrected, and no more than a couple of cards a day. Every failure is written down with the rule that caused it.",
  },
  {
    step: "Recognition",
    title: "The card you see",
    body: "Written in the second person, hedged to match its confidence, and never repeating your words back verbatim — so deleting a message really removes its text.",
  },
  {
    step: "Provenance",
    title: "The receipts",
    body: "Each card carries a frozen copy of the quotes, their dates and the conversation they came from, with a link that jumps to the exact span in the thread.",
  },
  {
    step: "Correction",
    title: "Your answer, kept",
    body: "Accept, correct, reject or set aside. A correction becomes a statement in your own words that enters the reasoning permanently: the prompt, the score, the gate, and how the chat talks to you.",
  },
] as const;

const STORED = [
  "Your messages, and your account details.",
  "Observations drawn from your messages, each with the quote and where it sits.",
  "What you told KnoRI, as a list you can read, edit, pin or retract.",
  "Recognitions, the evidence behind them, and what you did about each one.",
  "Your corrections, word for word, as durable statements.",
] as const;

const INFERRED = [
  "Patterns, preferences, values and tensions — and only those four.",
  "Always from at least two things you said, on at least two days.",
  "Never health, mental health, sexual orientation, religion, ethnicity, immigration status, criminal matters, politics or financial distress.",
  "Never anything about anyone else. Other people appear only as your own words about them.",
] as const;

export default function HowItWorksPage() {
  return (
    <>
      <div className="border-b border-line">
        <Section spacing="none" className="pb-16 pt-16 sm:pb-20 sm:pt-20">
          <div className="max-w-3xl">
            <p className="knori-eyebrow">How it works</p>
            <h1 className="mt-5 text-3xl sm:text-4xl">
              From something you typed to something you can check
            </h1>
            <p className="knori-prose mt-6 text-lg">
              There are eight steps between a message and a Recognition. Each one leaves a record,
              which is why KnoRI can always answer the only question that matters: why do you think
              that about me?
            </p>
          </div>
        </Section>
      </div>

      <Section aria-labelledby="loop-title">
        <SectionHeading eyebrow="The loop" title={<span id="loop-title">Eight steps</span>} />
        <ol className="mt-12 flex flex-col">
          {LOOP.map((entry, index) => (
            <li
              key={entry.step}
              className="grid gap-x-8 gap-y-2 border-t border-line py-7 sm:grid-cols-12"
            >
              <div className="sm:col-span-3">
                <p className="knori-eyebrow text-accent">
                  {String(index + 1).padStart(2, "0")} · {entry.step}
                </p>
              </div>
              <div className="sm:col-span-9">
                <h3 className="font-serif text-lg text-ink">{entry.title}</h3>
                <p className="mt-2 max-w-2xl text-base leading-relaxed text-ink-secondary">
                  {entry.body}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <div className="border-y border-line bg-sunken/50">
        <Section aria-labelledby="data-title">
          <SectionHeading
            eyebrow="Your side of it"
            title={<span id="data-title">What is stored, what is inferred, how to leave</span>}
          />
          <div className="mt-12 grid gap-6 lg:grid-cols-3">
            <Card>
              <CardBody>
                <h3 className="font-serif text-lg text-ink">What is stored</h3>
                <ul className="mt-4 flex flex-col gap-3">
                  {STORED.map((line) => (
                    <li key={line} className="text-base leading-relaxed text-ink-secondary">
                      {line}
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
            <Card>
              <CardBody>
                <h3 className="font-serif text-lg text-ink">What is inferred</h3>
                <ul className="mt-4 flex flex-col gap-3">
                  {INFERRED.map((line) => (
                    <li key={line} className="text-base leading-relaxed text-ink-secondary">
                      {line}
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
            <Card tone="recognition">
              <CardBody>
                <h3 className="font-serif text-lg text-ink">How to leave</h3>
                <div className="mt-4 flex flex-col gap-3 text-base leading-relaxed text-ink-secondary">
                  <p>
                    Export everything as one JSON file: conversations, messages, memory,
                    Recognitions with their evidence, and every correction you made.
                  </p>
                  <p>
                    Delete your account and it is gone after a day&rsquo;s grace — every row, in
                    every table. Backups age out within thirty days.
                  </p>
                  <p>
                    Delete one message and the quotes taken from it are scrubbed in the same
                    transaction. A card that loses its evidence is withdrawn.
                  </p>
                </div>
              </CardBody>
            </Card>
          </div>
        </Section>
      </div>

      <Section spacing="tight" className="pb-24">
        <div className="mx-auto max-w-xl text-center">
          <h2 className="text-2xl">Ready to try it?</h2>
          <p className="knori-prose mt-3">
            KnoRI is invite only during the beta. Ask for a code and we will write back.
          </p>
          <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
            <Link href="/signup" className={buttonStyles("primary", "lg")}>
              Request an invite
            </Link>
            <Link href="/legal/privacy" className={buttonStyles("secondary", "lg")}>
              Read the privacy note
            </Link>
          </div>
        </div>
      </Section>
    </>
  );
}
