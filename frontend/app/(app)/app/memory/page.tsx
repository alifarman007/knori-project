"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { IconMemory, IconPlus } from "@/components/icons";
import { AssertionsPanel } from "@/components/memory/assertions-panel";
import { MemoryEditor } from "@/components/memory/memory-editor";
import { MemoryItemRow } from "@/components/memory/memory-item-row";
import { ProfilePanel } from "@/components/memory/profile-panel";
import { PageHeader, PageShell } from "@/components/shell/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { memory } from "@/lib/endpoints";
import { MEMORY_KIND_LABEL, MEMORY_KIND_ORDER } from "@/lib/labels";
import { keys } from "@/lib/query-keys";
import { useSession } from "@/lib/session";
import type { MemoryItem, MemoryKind, Uuid } from "@/lib/types";
import { useErrorToast } from "@/lib/use-error-toast";

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const reportError = useErrorToast();
  const { settings } = useSession();

  const [editing, setEditing] = React.useState<MemoryItem | null>(null);
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [showRetracted, setShowRetracted] = React.useState(false);
  const [busyId, setBusyId] = React.useState<Uuid | null>(null);

  const query = useQuery({ queryKey: keys.memoryItems, queryFn: () => memory.items() });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: keys.memoryItems });
    void queryClient.invalidateQueries({ queryKey: keys.memoryProfile });
  }

  const save = useMutation({
    mutationFn: (input: { kind: MemoryKind; statement: string }) =>
      editing
        ? memory.update(editing.id, { statement: input.statement })
        : memory.add({ kind: input.kind, statement: input.statement }),
    onSuccess: () => {
      toast({ title: editing ? "Saved" : "KnoRI will remember that", tone: "positive" });
      setEditorOpen(false);
      setEditing(null);
      refresh();
    },
    onError: (error) => reportError(error, "That could not be saved"),
  });

  const patch = useMutation({
    mutationFn: (input: { item: MemoryItem; pinned: boolean }) =>
      memory.update(input.item.id, { pinned: input.pinned }),
    onMutate: (input) => setBusyId(input.item.id),
    onError: (error) => reportError(error, "That could not be changed"),
    onSettled: () => {
      setBusyId(null);
      refresh();
    },
  });

  const retract = useMutation({
    mutationFn: (item: MemoryItem) => memory.retract(item.id),
    onMutate: (item) => setBusyId(item.id),
    onSuccess: () => toast({ title: "Retracted", description: "KnoRI will not use it again." }),
    onError: (error) => reportError(error, "That could not be retracted"),
    onSettled: () => {
      setBusyId(null);
      refresh();
    },
  });

  const items = query.data ?? [];
  const visible = showRetracted ? items : items.filter((item) => item.status !== "retracted");
  const retractedCount = items.filter((item) => item.status === "retracted").length;

  const grouped = React.useMemo(() => {
    const map = new Map<MemoryKind, MemoryItem[]>();
    for (const item of visible) {
      const list = map.get(item.kind) ?? [];
      list.push(item);
      map.set(item.kind, list);
    }
    for (const list of map.values()) {
      // Pinned first, then what KnoRI heard most recently.
      list.sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return (b.last_confirmed_at ?? b.first_seen_at).localeCompare(
          a.last_confirmed_at ?? a.first_seen_at,
        );
      });
    }
    return map;
  }, [visible]);

  function openEditor(item: MemoryItem | null) {
    setEditing(item);
    setEditorOpen(true);
  }

  return (
    <PageShell className="pb-16">
      <PageHeader
        title="Memory"
        description="Everything you told KnoRI, in your own words, with the message each one came from."
        action={
          <Button variant="secondary" onClick={() => openEditor(null)}>
            <IconPlus className="size-4" />
            Add something
          </Button>
        }
      />

      {settings && !settings.memory_enabled ? (
        <Alert tone="info" title="Memory is switched off" className="mb-6">
          Nothing new is being remembered. What is already here stays until you retract it, and the
          switch is on Settings.
        </Alert>
      ) : null}

      <ProfilePanel />

      <section className="mt-10" aria-labelledby="what-you-told">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="what-you-told" className="font-serif text-lg text-ink">
              What you told KnoRI
            </h2>
            <p className="mt-1.5 text-base text-ink-muted">
              Edit anything. An edited memory is never overwritten by the machine again.
            </p>
          </div>
          {retractedCount > 0 ? (
            <Switch
              checked={showRetracted}
              onCheckedChange={setShowRetracted}
              label="Show retracted"
              className="w-auto gap-3"
            />
          ) : null}
        </div>

        {query.isPending ? (
          <SkeletonText lines={6} className="mt-6" />
        ) : query.isError ? (
          <Alert tone="danger" title="This could not be loaded" className="mt-6">
            <Button
              size="sm"
              variant="secondary"
              className="mt-2"
              onClick={() => void query.refetch()}
            >
              Try again
            </Button>
          </Alert>
        ) : visible.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<IconMemory className="size-8" />}
            title="Nothing remembered yet"
            description="KnoRI keeps what you tell it in conversation — a plan, a preference, something that happened. Talk for a while and this fills itself in."
            action={
              <Button variant="secondary" onClick={() => openEditor(null)}>
                Or tell it something now
              </Button>
            }
          />
        ) : (
          <div className="mt-6 flex flex-col gap-8">
            {MEMORY_KIND_ORDER.filter((kind) => grouped.has(kind)).map((kind) => (
              <div key={kind}>
                <h3 className="knori-eyebrow">{MEMORY_KIND_LABEL[kind]}</h3>
                <ul className="mt-2">
                  {(grouped.get(kind) ?? []).map((item) => (
                    <MemoryItemRow
                      key={item.id}
                      item={item}
                      busy={busyId === item.id}
                      onEdit={openEditor}
                      onTogglePin={(target) =>
                        patch.mutate({ item: target, pinned: !target.pinned })
                      }
                      onRetract={(target) => retract.mutate(target)}
                    />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <AssertionsPanel className="mt-12 border-t border-line pt-8" />

      <MemoryEditor
        open={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        item={editing}
        saving={save.isPending}
        onSave={(input) => save.mutate(input)}
      />
    </PageShell>
  );
}
