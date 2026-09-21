import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { confidenceInWords } from "@/lib/format";
import type { ConfidenceLabel } from "@/lib/types";

export interface ConfidenceBadgeProps {
  label: ConfidenceLabel;
  className?: string;
}

/**
 * "likely" or "strong" — never a percentage. A number invites the person to
 * argue with the arithmetic instead of with the claim.
 */
export function ConfidenceBadge({ label, className }: ConfidenceBadgeProps) {
  return (
    <Tooltip content={confidenceInWords(label)} className={className}>
      <Badge
        tone={label === "strong" ? "accent" : "outline"}
        mono
        dot={label === "strong"}
        className="cursor-help"
      >
        {label}
        <span aria-hidden="true" className="ml-0.5 opacity-60">
          ?
        </span>
      </Badge>
    </Tooltip>
  );
}
