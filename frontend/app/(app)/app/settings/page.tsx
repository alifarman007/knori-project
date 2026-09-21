"use client";

import Link from "next/link";
import * as React from "react";

import { PasswordForm } from "@/components/settings/password-form";
import { MemoryPreference, Preferences } from "@/components/settings/preferences";
import { DataStatement, DeleteAccount, ExportData } from "@/components/settings/privacy";
import { ProfileForm } from "@/components/settings/profile-form";
import { SettingSection } from "@/components/settings/setting-section";
import { PageHeader, PageShell } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { auth } from "@/lib/endpoints";
import { useSession } from "@/lib/session";
import { useErrorToast } from "@/lib/use-error-toast";

export default function SettingsPage() {
  const { user } = useSession();
  const reportError = useErrorToast();
  const [signingOut, setSigningOut] = React.useState(false);

  async function signOut() {
    setSigningOut(true);
    try {
      await auth.logout();
      window.location.href = "/login";
    } catch (error) {
      reportError(error, "You could not be signed out");
      setSigningOut(false);
    }
  }

  return (
    <PageShell className="pb-16">
      <PageHeader
        title="Settings"
        description="Your account, and how much KnoRI is allowed to notice."
        action={
          <Button variant="secondary" loading={signingOut} onClick={() => void signOut()}>
            Sign out
          </Button>
        }
      />

      <SettingSection
        id="profile"
        eyebrow="01"
        title="You"
        description={user ? `Signed in as ${user.email}.` : undefined}
      >
        <ProfileForm />
      </SettingSection>

      <SettingSection
        id="recognition"
        eyebrow="02"
        title="Recognition"
        description="What KnoRI is allowed to tell you, and how often."
      >
        <Preferences />
      </SettingSection>

      <SettingSection
        id="memory"
        eyebrow="03"
        title="Memory"
        description="What KnoRI is allowed to keep."
      >
        <MemoryPreference />
      </SettingSection>

      <SettingSection
        id="password"
        eyebrow="04"
        title="Password"
        description="Changing it signs out every other session."
      >
        <PasswordForm />
      </SettingSection>

      <SettingSection
        id="your-data"
        eyebrow="05"
        title="Your data"
        description="Take it with you at any time."
      >
        <ExportData />
      </SettingSection>

      <SettingSection
        id="what-is-stored"
        eyebrow="06"
        title="What is stored"
        description={
          <>
            The full version is in the{" "}
            <Link href="/legal/privacy" className="underline underline-offset-4 hover:text-ink">
              privacy note
            </Link>
            .
          </>
        }
      >
        <DataStatement />
      </SettingSection>

      <SettingSection
        id="delete"
        eyebrow="07"
        title="Leaving"
        description="No questions, and no dark pattern in the way."
      >
        <DeleteAccount />
      </SettingSection>
    </PageShell>
  );
}
