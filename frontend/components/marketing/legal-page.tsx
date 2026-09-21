import { Section } from "@/components/marketing/section";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

export interface LegalSection {
  heading: string;
  paragraphs: readonly string[];
}

export interface LegalPageProps {
  title: string;
  /** The version recorded against a person's acceptance, e.g. "draft-0". */
  version: string;
  updated: string;
  intro: string;
  sections: readonly LegalSection[];
}

/**
 * Shared shell for the two legal documents.
 *
 * The draft-0 banner is deliberate and stays until a lawyer has replaced the
 * text: the version string shown here is the one recorded against a person's
 * acceptance, so it must never quietly disagree with the document.
 */
export function LegalPage({ title, version, updated, intro, sections }: LegalPageProps) {
  return (
    <Section spacing="none" className="max-w-3xl pb-24 pt-16">
      <div className="flex flex-wrap items-center gap-3">
        <p className="knori-eyebrow">Legal</p>
        <Badge tone="outline" mono>
          version {version}
        </Badge>
      </div>

      <h1 className="mt-5 text-3xl sm:text-4xl">{title}</h1>
      <p className="mt-3 text-sm text-ink-muted">Last updated {updated}</p>

      <Alert tone="danger" title="Placeholder text — not legal advice" className="mt-8">
        This is a working draft written so the product can be built and tested end to end. It has
        not been reviewed by a lawyer and must be replaced before anyone outside the beta signs up.
        Acceptances recorded against <span className="font-mono">{version}</span> will be collected
        again when the final text lands.
      </Alert>

      <p className="knori-prose mt-8">{intro}</p>

      <div className="mt-10 flex flex-col gap-9">
        {sections.map((section, index) => (
          <section key={section.heading}>
            <h2 className="flex items-baseline gap-3 text-xl">
              <span className="knori-eyebrow font-sans text-accent">
                {String(index + 1).padStart(2, "0")}
              </span>
              {section.heading}
            </h2>
            <div className="knori-prose mt-3">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </section>
        ))}
      </div>
    </Section>
  );
}
