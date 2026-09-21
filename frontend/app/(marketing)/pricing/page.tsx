import type { Metadata } from "next";
import Link from "next/link";

import { IconCheck } from "@/components/icons";
import { Section, SectionHeading } from "@/components/marketing/section";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonStyles } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "What KnoRI will cost, and why nothing is charged inside the app during the invite-only beta.",
};

const PLANS = [
  {
    name: "Beta",
    price: "Free",
    cadence: "while we are in beta",
    summary: "For the people helping us find out whether this works.",
    features: [
      "Unlimited conversations",
      "Memory you can read and edit",
      "Up to two Recognitions a day",
      "Full export, delete any time",
    ],
    cta: { href: "/signup", label: "Request an invite" },
    featured: true,
  },
  {
    name: "Personal",
    price: "$18",
    cadence: "per month, when we open",
    summary: "The everyday version, for one person.",
    features: [
      "Everything in Beta",
      "Longer memory retention",
      "Recognition history and revisions",
      "Email support",
    ],
    cta: { href: "/signup", label: "Join the waitlist" },
    featured: false,
  },
  {
    name: "Practice",
    price: "Talk to us",
    cadence: "for teams and practitioners",
    summary: "For people who need this alongside their work with others.",
    features: [
      "Everything in Personal",
      "Data processing agreement",
      "Shared billing",
      "Onboarding session",
    ],
    cta: { href: "mailto:hello@knori.app", label: "Get in touch" },
    featured: false,
  },
] as const;

export default function PricingPage() {
  return (
    <>
      <Section spacing="none" className="pb-10 pt-16 sm:pt-20">
        <SectionHeading
          align="center"
          eyebrow="Pricing"
          title="Simple, and not charged yet"
          lede="KnoRI is invite only while it is in beta. Nothing is billed inside the app today — the plans below are what it will cost when it opens."
        />
      </Section>

      <Section spacing="none">
        <div className="grid gap-6 lg:grid-cols-3">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={cn(
                "flex flex-col rounded-lg border bg-surface p-7",
                plan.featured ? "border-accent-line shadow-lift" : "border-line shadow-soft",
              )}
            >
              <div className="flex items-center gap-2">
                <h2 className="font-serif text-lg text-ink">{plan.name}</h2>
                {plan.featured ? (
                  <Badge tone="accent" mono>
                    now
                  </Badge>
                ) : null}
              </div>
              <p className="mt-4 flex items-baseline gap-2">
                <span className="font-serif text-3xl text-ink">{plan.price}</span>
              </p>
              <p className="mt-1 text-sm text-ink-muted">{plan.cadence}</p>
              <p className="mt-4 text-base leading-relaxed text-ink-secondary">{plan.summary}</p>

              <ul className="mt-6 flex flex-1 flex-col gap-3">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2.5 text-base text-ink-secondary">
                    <IconCheck className="mt-[3px] size-4 shrink-0 text-accent" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>

              <Link
                href={plan.cta.href}
                className={cn(
                  buttonStyles(plan.featured ? "primary" : "secondary", "md", "mt-8 w-full"),
                )}
              >
                {plan.cta.label}
              </Link>
            </div>
          ))}
        </div>
      </Section>

      <Section spacing="none" className="pb-24 pt-16">
        <div className="mx-auto max-w-2xl">
          <Alert tone="accent" title="Why there is no payment form here">
            <p>
              During the beta, signup needs an invite code and payment is arranged outside the app.
              That keeps the cost of running the models under control while a small group uses it
              properly, and it keeps card details out of a product that is still being built.
            </p>
          </Alert>

          <div className="mt-10 flex flex-col gap-6">
            <div>
              <h3 className="font-serif text-lg text-ink">Can I export my data if I leave?</h3>
              <p className="mt-2 text-base leading-relaxed text-ink-secondary">
                Yes — one JSON file with every conversation, every memory, every Recognition and its
                evidence, and every correction you made. No request form, no waiting period.
              </p>
            </div>
            <div>
              <h3 className="font-serif text-lg text-ink">What happens to my data if I stop?</h3>
              <p className="mt-2 text-base leading-relaxed text-ink-secondary">
                Deleting your account removes every row belonging to you after one day of grace, so
                an accident can be undone. Backups age out within thirty days.
              </p>
            </div>
            <div>
              <h3 className="font-serif text-lg text-ink">Is my chat used to train models?</h3>
              <p className="mt-2 text-base leading-relaxed text-ink-secondary">
                No. Your conversations are sent to the model providers only to produce your replies
                and your Recognitions, and are not retained by them for training.
              </p>
            </div>
          </div>
        </div>
      </Section>
    </>
  );
}
