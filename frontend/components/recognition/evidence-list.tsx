import { chatDeepLink, EvidenceQuote } from "@/components/recognition/evidence-quote";
import type { ProvenanceItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface EvidenceListProps {
  items: readonly ProvenanceItem[];
  className?: string;
}

function order(items: readonly ProvenanceItem[]): ProvenanceItem[] {
  return [...items].sort((a, b) => a.display_order - b.display_order);
}

/**
 * The evidence, in three groups.
 *
 * Contradicting quotes get their own heading rather than being mixed in: a
 * product that shows you only what supports its own claim is doing something
 * else. If KnoRI counted something against itself and went ahead anyway, the
 * person should be able to see that in one glance.
 */
export function EvidenceList({ items, className }: EvidenceListProps) {
  const supports = order(items.filter((item) => item.role === "supports"));
  const contradicts = order(items.filter((item) => item.role === "contradicts"));
  const context = order(items.filter((item) => item.role === "context"));

  return (
    <div className={cn("flex flex-col gap-8", className)}>
      <section aria-labelledby="evidence-supports">
        <h3 id="evidence-supports" className="knori-eyebrow">
          What it is built on
        </h3>
        {supports.length === 0 ? (
          <p className="mt-3 text-base text-ink-muted">
            The supporting quotes are no longer available.
          </p>
        ) : (
          <ul className="mt-4 flex flex-col gap-5">
            {supports.map((item) => (
              <EvidenceQuote key={item.id} item={item} hrefFor={chatDeepLink} />
            ))}
          </ul>
        )}
      </section>

      {contradicts.length > 0 ? (
        <section aria-labelledby="evidence-contradicts">
          <h3 id="evidence-contradicts" className="knori-eyebrow text-danger">
            What pulls against it
          </h3>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            KnoRI counted these too. They lowered its confidence without cancelling the pattern.
          </p>
          <ul className="mt-4 flex flex-col gap-5">
            {contradicts.map((item) => (
              <EvidenceQuote key={item.id} item={item} hrefFor={chatDeepLink} />
            ))}
          </ul>
        </section>
      ) : null}

      {context.length > 0 ? (
        <section aria-labelledby="evidence-context">
          <h3 id="evidence-context" className="knori-eyebrow">
            Around it
          </h3>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            Kept for context. These did not count towards the claim.
          </p>
          <ul className="mt-4 flex flex-col gap-5">
            {context.map((item) => (
              <EvidenceQuote key={item.id} item={item} hrefFor={chatDeepLink} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
