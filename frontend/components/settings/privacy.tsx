"use client";

import * as React from "react";

import { IconDownload } from "@/components/icons";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { download } from "@/lib/api";
import { EXPORT_PATH, me as meApi } from "@/lib/endpoints";
import { useErrorToast } from "@/lib/use-error-toast";

/** Export everything as one JSON file. */
export function ExportData() {
  const [busy, setBusy] = React.useState(false);
  const { toast } = useToast();
  const reportError = useErrorToast();

  async function run() {
    setBusy(true);
    try {
      const stamp = new Date().toISOString().slice(0, 10);
      await download(EXPORT_PATH, `knori-export-${stamp}.json`);
      toast({ title: "Downloaded", tone: "positive" });
    } catch (error) {
      reportError(error, "The export could not be made");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Button variant="secondary" loading={busy} loadingText="Preparing…" onClick={() => void run()}>
        <IconDownload className="size-4" />
        Download everything
      </Button>
      <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-muted">
        One JSON file: every conversation and message, everything KnoRI remembers, every
        Recognition with the quotes behind it, what you answered, and every correction you made.
      </p>
    </div>
  );
}

/**
 * Deleting the account.
 *
 * The password is asked for because this is irreversible after the grace
 * window, and the grace window is explained before the button rather than in a
 * confirmation nobody reads.
 */
export function DeleteAccount() {
  const [open, setOpen] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | undefined>(undefined);
  const [busy, setBusy] = React.useState(false);
  const reportError = useErrorToast();

  async function confirm() {
    if (!password) {
      setError("Enter your password to confirm.");
      return;
    }
    setBusy(true);
    try {
      await meApi.deleteAccount(password);
      window.location.href = "/login?deleted=1";
    } catch (cause) {
      reportError(cause, "The account could not be deleted");
      setBusy(false);
    }
  }

  return (
    <div>
      <Alert tone="danger" title="You have a day to change your mind">
        Deleting marks the account for removal and signs you out. For 24 hours you can sign back in
        and undo it. After that everything is destroyed: conversations, memory, Recognitions and
        the quotes behind them.
      </Alert>

      <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-muted">
        Encrypted backups are kept on a rolling schedule and are overwritten in the normal course of
        things, so a copy of your data can survive in a backup for up to 30 days after deletion. It
        is never restored into the live product except to recover from a failure of the whole
        database.
      </p>

      <Button variant="danger" className="mt-5" onClick={() => setOpen(true)}>
        Delete my account
      </Button>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Delete your account?"
        description="You can undo this for 24 hours by signing in again. After that it cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Keep my account
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void confirm()}>
              Delete it
            </Button>
          </>
        }
      >
        <Field label="Your password" error={error}>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              if (error) setError(undefined);
            }}
          />
        </Field>
      </Dialog>
    </div>
  );
}

/** The plain-language statement, in one block so it can be read in one go. */
export function DataStatement() {
  return (
    <div className="knori-prose max-w-prose text-base">
      <p>
        KnoRI stores what you type, what it replied, and the short statements it took from your
        messages — each one with the exact words it came from and the day you said them. Nothing
        about anybody else is stored as a fact; your own words about other people stay your words.
      </p>
      <p>
        Your messages are sent to Anthropic and OpenAI to produce replies and to work out what to
        remember. They are not used to train anybody&rsquo;s models. Nothing is sold, and nothing is
        shared with anyone else.
      </p>
      <p>
        Deleting a message removes its text and blanks the quotes taken from it, in the same
        transaction — a Recognition built on it keeps the fact that something counted, but the words
        are gone. Deleting your account removes everything.
      </p>
    </div>
  );
}
