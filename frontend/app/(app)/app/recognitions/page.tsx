"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { IconRecognition } from "@/components/icons";
import { AskButton } from "@/components/recognition/ask-button";
import { FirstRecognitionExplainer } from "@/components/recognition/first-recognition-explainer";
import { RecognitionList } from "@/components/recognition/recognition-list";
import { PageHeader, PageShell } from "@/components/shell/page-header";
import { Tab, TabPanel, Tabs, TabsList } from "@/components/ui/tabs";
import type { EmptyStateProps } from "@/components/ui/empty-state";
import { recognitions } from "@/lib/endpoints";
import { keys } from "@/lib/query-keys";
import type { RecognitionState, RecognitionSummary } from "@/lib/types";

interface TabSpec {
  value: string;
  label: string;
  states: readonly RecognitionState[];
  count: (summary: RecognitionSummary | undefined) => number | undefined;
  empty: EmptyStateProps;
}

const icon = <IconRecognition className="size-8" />;

const TABS: readonly TabSpec[] = [
  {
    value: "new",
    label: "New",
    states: ["pending", "presented"],
    count: (summary) => summary?.new,
    empty: {
      icon,
      title: "Nothing yet — and that is the point",
      description:
        "KnoRI needs a few conversations across different days. It will not turn one evening into a claim about you: it wants at least two things you said, on two different calendar days, twelve hours apart, before it says anything at all.",
      footnote: "Keep talking. There is nothing to configure.",
    },
  },
  {
    value: "accepted",
    label: "Accepted",
    states: ["accepted"],
    count: (summary) => summary?.accepted,
    empty: {
      icon,
      title: "Nothing accepted yet",
      description:
        "Cards you confirm live here, and the chat may refer to them by name once you have.",
    },
  },
  {
    value: "corrected",
    label: "Corrected",
    states: ["corrected"],
    count: (summary) => summary?.corrected,
    empty: {
      icon,
      title: "Nothing corrected yet",
      description:
        "When you correct a card, your words are kept here next to what the correction changed.",
    },
  },
  {
    value: "rejected",
    label: "Rejected",
    states: ["rejected"],
    count: (summary) => summary?.rejected,
    empty: {
      icon,
      title: "Nothing rejected",
      description: "Claims you reject stay here, so you can see what KnoRI got wrong and when.",
    },
  },
  {
    value: "dismissed",
    label: "Set aside",
    states: ["dismissed", "withdrawn"],
    count: (summary) => summary?.dismissed,
    empty: {
      icon,
      title: "Nothing set aside",
      description: "Cards you were not ready for, and ones KnoRI withdrew, wait here quietly.",
    },
  },
];

export default function RecognitionsPage() {
  const [tab, setTab] = React.useState("new");

  const summary = useQuery({
    queryKey: keys.recognitionSummary,
    queryFn: recognitions.summary,
  });

  const hasAny = Object.values(summary.data ?? {}).some(
    (value) => typeof value === "number" && value > 0,
  );

  return (
    <PageShell>
      <FirstRecognitionExplainer enabled={(summary.data?.new ?? 0) > 0} />

      <PageHeader
        title="Recognitions"
        description="Everything KnoRI has noticed, the words behind each one, and what you said back."
        action={<AskButton />}
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Recognition states">
          {TABS.map((entry) => (
            <Tab key={entry.value} value={entry.value} count={entry.count(summary.data)}>
              {entry.label}
            </Tab>
          ))}
        </TabsList>

        {TABS.map((entry) => (
          <TabPanel key={entry.value} value={entry.value} className="pt-6">
            <RecognitionList tab={entry.value} empty={entry.empty} />
          </TabPanel>
        ))}
      </Tabs>

      {!hasAny && !summary.isPending ? (
        <p className="mt-8 border-t border-line pt-6 text-sm leading-relaxed text-ink-muted">
          KnoRI does not look for patterns while you are typing. It reads what you have said after
          the fact, on a schedule — so the first card usually appears a day or two in, not in your
          first conversation.
        </p>
      ) : null}
    </PageShell>
  );
}
