import Link from "next/link";

import { IconArrowRight, IconScales, IconShield } from "@/components/icons";
import { SampleRecognition } from "@/components/marketing/sample-recognition";
import { Section, SectionHeading } from "@/components/marketing/section";
import { buttonStyles } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STEPS = [
  {
    number: "01",
    title: "You talk",
    body: "An ordinary chat. Work, a decision you keep circling, the thing you did not say out loud yet. Nothing to fill in, no profile to set up.",
  },
  {
    number: "02",
    title: "KnoRI remembers",
    body: "It keeps what you actually said, with the message it came from. You can open that list any time, edit it, pin it, or take something back.",
  },
  {
    number: "03",
    title: "It recognises — with evidence",
    body: "When enough of it points the same way, on different days, you get one card: the pattern, and the exact words behind it. You can accept, correct, reject or set it aside.",
  },
] as const;

const GUARDS = [
  {
    tag: "R3",
    title: "One sentence is never a pattern",
    body: "A Recognition needs at least two things you said, on two different calendar days, at least twelve hours apart. One message, one sitting, one long evening — none of them can become a claim about you.",
  },
  {
    tag: "Evidence",
    title: "Every claim shows its receipts",
    body: "Each card carries the quotes it was built from, checked character by character against your original message. If a quote cannot be located exactly, the evidence is thrown away rather than approximated.",
  },
  {
    tag: "Your words",
    title: "Only what you said about yourself",
    body: "Things you quote from other people, hypotheticals and jokes are marked as such and never become evidence. KnoRI keeps no records about anybody but you.",
  },
  {
    tag: "Correction",
    title: "Correcting it actually changes it",
    body: "A correction is stored as your own statement and goes into the reasoning from then on — the prompt, the score, the gate that blocks the claim, and how the chat talks to you. It is not a hide button.",
  },
] as const;

const NOT = [
  "Not a therapist, and not a diagnosis. Health, mental health, religion, politics and the rest are never inferred from.",
  "Not a personality test. There is no type, no score out of five, no chart of you.",
  "Not a data broker. Your conversations are not training data and are not sold.",
  "Not a system that guesses. If it cannot show you why, it does not say it.",
  "Not keeping anything you delete. Delete a message and the quotes taken from it are scrubbed in the same breath.",
] as const;

export default function LandingPage() {
  return (
    <>
      {/* ---------------------------------------------------------- hero */}
      <div className="relative overflow-hidden border-b border-line">
        <div
          aria-hidden="true"
          className="knori-ruled pointer-events-none absolute inset-0 opacity-[0.55] [mask-image:linear-gradient(to_bottom,black,transparent_78%)]"
        />
        <div className="knori-gutter relative mx-auto w-full max-w-6xl pb-20 pt-16 sm:pb-28 sm:pt-24">
          <div className="grid gap-12 lg:grid-cols-12 lg:gap-8">
            <div className="lg:col-span-7">
              <p className="knori-eyebrow motion-safe:animate-rise">Invite only · in beta</p>
              <h1
                className="mt-5 text-4xl leading-[1.06] sm:text-5xl motion-safe:animate-rise"
                style={{ animationDelay: "60ms" }}
              >
                You have been saying this for a while.
              </h1>
              <p
                className="knori-prose mt-6 max-w-xl text-lg motion-safe:animate-rise"
                style={{ animationDelay: "120ms" }}
              >
                KnoRI is a chat that remembers what you tell it. When enough of it points the same
                way — on different days, not in one sitting — it shows you the pattern it noticed,
                and the exact words it came from.
              </p>
              <div
                className="mt-9 flex flex-col gap-3 sm:flex-row motion-safe:animate-rise"
                style={{ animationDelay: "180ms" }}
              >
                <Link href="/signup" className={buttonStyles("primary", "lg")}>
                  Request an invite
                </Link>
                <Link href="/how-it-works" className={cn(buttonStyles("ghost", "lg"), "group")}>
                  See how it works
                  <IconArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </div>

            <aside
              className="relative lg:col-span-4 lg:col-start-9 lg:pt-24 motion-safe:animate-rise"
              style={{ animationDelay: "240ms" }}
            >
              <div className="border-l-2 border-accent-line pl-5">
                <p className="knori-eyebrow">In the margin</p>
                <p className="mt-3 font-serif text-md italic leading-relaxed text-ink-secondary">
                  A pattern that can be built from one evening is not a pattern. KnoRI needs two
                  different days and twelve hours between them before it will say anything at all.
                </p>
                <p className="mt-3 text-sm text-ink-muted">
                  It is the rule that makes the rest worth reading.
                </p>
              </div>
            </aside>
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------- steps */}
      <Section aria-labelledby="steps-title">
        <SectionHeading
          eyebrow="Three steps"
          title={<span id="steps-title">You talk. It remembers. It recognises.</span>}
        />
        <ol className="mt-12 grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-3">
          {STEPS.map((step) => (
            <li key={step.number} className="flex flex-col gap-3 bg-surface p-7">
              <span className="knori-eyebrow text-accent">{step.number}</span>
              <h3 className="font-serif text-lg text-ink">{step.title}</h3>
              <p className="text-base leading-relaxed text-ink-secondary">{step.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      {/* -------------------------------------------------- sample card */}
      <div className="border-y border-line bg-sunken/50">
        <Section aria-labelledby="sample-title">
          <div className="grid gap-12 lg:grid-cols-12 lg:gap-10">
            <div className="lg:col-span-4">
              <SectionHeading
                eyebrow="What you get"
                title={<span id="sample-title">One card. Nothing hidden behind it.</span>}
                lede="This is a real card, with the evidence already open. In the product it arrives in the middle of a conversation, once — never as a stream of notifications."
              />
              <p className="mt-6 text-sm text-ink-muted">
                Try the four buttons. Nothing is saved here.
              </p>
            </div>
            <div className="lg:col-span-7 lg:col-start-6">
              <SampleRecognition />
            </div>
          </div>
        </Section>
      </div>

      {/* -------------------------------------------------------- guards */}
      <Section aria-labelledby="guards-title">
        <SectionHeading
          eyebrow="Knowing when not to speak"
          title={<span id="guards-title">The rules that stop it guessing</span>}
          lede="Most of the engineering in KnoRI went into the cases where it stays quiet. Every decision not to say something is written down, with the rule that blocked it."
        />
        <div className="mt-12 grid gap-x-10 gap-y-10 sm:grid-cols-2">
          {GUARDS.map((guard) => (
            <div key={guard.tag} className="border-t border-line pt-5">
              <p className="knori-eyebrow text-accent">{guard.tag}</p>
              <h3 className="mt-2 font-serif text-lg text-ink">{guard.title}</h3>
              <p className="mt-2 text-base leading-relaxed text-ink-secondary">{guard.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* ------------------------------------------------------- what not */}
      <div className="border-y border-line bg-sunken/50">
        <Section aria-labelledby="not-title">
          <div className="grid gap-10 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <SectionHeading
                eyebrow="Plainly"
                title={<span id="not-title">What KnoRI is not</span>}
              />
              <IconShield className="mt-8 size-10 text-accent" />
            </div>
            <ul className="flex flex-col gap-4 lg:col-span-7 lg:col-start-6">
              {NOT.map((line) => (
                <li key={line} className="flex gap-3 border-b border-line pb-4 last:border-0">
                  <span
                    aria-hidden="true"
                    className="mt-[0.7em] h-px w-5 shrink-0 bg-line-strong"
                  />
                  <span className="text-base leading-relaxed text-ink-secondary">{line}</span>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      </div>

      {/* ------------------------------------------------------------ cta */}
      <Section>
        <div className="mx-auto max-w-2xl text-center">
          <IconScales className="mx-auto size-8 text-accent" />
          <h2 className="mt-6 text-2xl sm:text-3xl">Worth being understood accurately</h2>
          <p className="knori-prose mt-4">
            KnoRI is invite only while it is in beta, so that everyone using it gets the attention
            it needs. Ask for a code and we will write back.
          </p>
          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
            <Link href="/signup" className={buttonStyles("primary", "lg")}>
              Request an invite
            </Link>
            <Link href="/pricing" className={buttonStyles("secondary", "lg")}>
              See the plans
            </Link>
          </div>
        </div>
      </Section>
    </>
  );
}
