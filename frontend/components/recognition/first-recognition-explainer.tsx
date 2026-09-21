"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

const STORAGE_KEY = "knori-first-card-seen";

/**
 * Shown once, the first time a card exists.
 *
 * A stranger telling you what it noticed about you is a strange moment, and it
 * deserves one paragraph of explanation before the four buttons. The flag is
 * per-browser: `user_settings.flags` is the right home for it, but no endpoint
 * exposes that yet, so a second device sees it once more rather than never.
 */
export function FirstRecognitionExplainer({ enabled }: { enabled: boolean }) {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (!enabled) return;
    try {
      if (localStorage.getItem(STORAGE_KEY)) return;
    } catch {
      return; // Blocked storage: never nag rather than nag every visit.
    }
    setOpen(true);
  }, [enabled]);

  function close() {
    setOpen(false);
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // Nothing to do; it simply shows again next time.
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="This is the part that matters"
      footer={<Button onClick={close}>Show me</Button>}
    >
      <div className="knori-prose">
        <p>
          KnoRI has put something together about you. It is not a diagnosis and it is not a summary
          of your personality — it is one pattern it thinks it can see, with the exact things you
          said underneath it.
        </p>
        <p>
          Open the evidence. If the quotes do not add up to the claim, say so. Correcting a card is
          not a complaint form: what you write becomes something KnoRI has to reason with from then
          on, and cards built on the old reading get withdrawn.
        </p>
      </div>
    </Dialog>
  );
}
