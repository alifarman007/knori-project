import { expect, test } from "@playwright/test";

import { installApiMock } from "./mock-api";

test("the landing page explains itself and shows a card with its evidence", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("saying this for a while");

  const card = page.getByRole("article");
  await expect(card.getByText(/based on 3 things you said across 2 days/)).toBeVisible();
  await expect(card.getByText(/until I've written it out properly/)).toBeVisible();

  // Every card offers all four answers, never just the agreeable one.
  for (const label of [/that.s right/i, /not quite/i, /not true/i, /not now/i]) {
    await expect(card.getByRole("button", { name: label })).toBeVisible();
  }
});

test("signup refuses to submit an empty form and says why, per field", async ({ page }) => {
  await page.goto("/signup");
  await page.getByRole("button", { name: /create account/i }).click();

  await expect(page.getByText(/tell knori what to call you/i)).toBeVisible();
  await expect(page.getByText(/invite code is needed/i)).toBeVisible();
  await expect(page.getByLabel(/email/i)).toHaveAttribute("aria-invalid", "true");
});

test("an unauthenticated visit to the app is sent to sign in, keeping where it was going", async ({
  page,
}) => {
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/problem+json",
      body: JSON.stringify({ title: "Please sign in", status: 401, code: "unauthorized" }),
    }),
  );

  await page.goto("/app/recognitions");
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Frecognitions/);
});

test("the app shell reaches all four sections", async ({ page }) => {
  await installApiMock(page, { onboardingComplete: true });
  await page.goto("/app/recognitions");

  const nav = page.getByRole("navigation", { name: "Sections" }).first();
  for (const label of ["Chat", "Recognitions", "Memory", "Settings"]) {
    await expect(nav.getByRole("link", { name: new RegExp(label) })).toBeVisible();
  }

  await expect(page.getByRole("tab", { name: /^New/ })).toHaveAttribute("aria-selected", "true");
});
