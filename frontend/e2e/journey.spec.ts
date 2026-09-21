import { expect, test } from "@playwright/test";

import { installApiMock, MOCK } from "./mock-api";

/**
 * The path a customer actually walks: sign up, answer three questions, talk,
 * meet a Recognition, open the evidence, correct it, see what changed.
 *
 * It runs against the mocked API in `mock-api.ts` — no backend, no keys.
 */

test("signup asks for an invite and confirms where the email went", async ({ page }) => {
  await installApiMock(page);
  await page.goto("/signup");

  await page.getByLabel(/what should knori call you/i).fill("Alif");
  await page.getByLabel(/^email$/i).fill("you@example.com");
  await page.getByLabel(/^password$/i).fill("a sentence i remember");
  await page.getByLabel(/invite code/i).fill("KNORI-1");
  await page.getByRole("button", { name: /create account/i }).click();

  await expect(page.getByRole("heading", { name: /check your email/i })).toBeVisible();
  await expect(page.getByText("you@example.com")).toBeVisible();
});

test("an unfinished account is sent to onboarding and walked through all three steps", async ({
  page,
}) => {
  await installApiMock(page);
  await page.goto("/app/chat");

  // Step 1 — about you.
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: /first, the basics/i })).toBeVisible();
  await page.getByLabel(/your name/i).fill("Alif");
  await page.getByRole("button", { name: /continue/i }).click();

  // Step 2 — consent, which will not pass without the box ticked.
  await expect(page.getByRole("heading", { name: /what you are agreeing to/i })).toBeVisible();
  await page.getByRole("button", { name: /i agree/i }).click();
  await expect(page.getByText(/tick the box/i)).toBeVisible();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /i agree/i }).click();

  // Step 3 — three questions, one at a time, as a conversation.
  await expect(page.getByText(/question 1 of 3/i)).toBeVisible();
  for (let index = 1; index <= 3; index += 1) {
    await page.getByLabel(/your answer/i).fill(`Answer number ${index}, at some length.`);
    await page.getByRole("button", { name: index === 3 ? /finish/i : /^send$/i }).click();
  }

  // "Here's what I noted", each line with the words it came from.
  await expect(page.getByRole("heading", { name: /here is what i noted/i })).toBeVisible();
  await expect(page.getByText(/Answer number 1/)).toBeVisible();
  await page.getByRole("button", { name: /start talking/i }).click();
  await expect(page).toHaveURL(/\/app\/chat/);
});

test("chat streams a reply and places the card where the evidence came from", async ({ page }) => {
  await installApiMock(page, { onboardingComplete: true });
  await page.goto("/app/chat");

  await expect(page).toHaveURL(new RegExp(`/app/chat/${MOCK.CONVERSATION_ID}`));
  await expect(page.locator("#m-1")).toContainText(MOCK.QUOTE_ONE);

  // The Recognition sits inline, after the message that tipped it over.
  const card = page.getByRole("article", { name: /you work things out on the page/i });
  await expect(card).toBeVisible();
  await expect(page.getByText(/knori noticed something here/i)).toBeVisible();

  // Enter sends; the reply arrives in pieces.
  const box = page.getByRole("textbox", { name: "Message" });
  await box.fill("wrote three pages last night");
  await box.press("Enter");
  await expect(page.getByText(/that tracks with what you said on tuesday/i)).toBeVisible();
});

test("a deep link scrolls to the message and marks exactly those characters", async ({ page }) => {
  await installApiMock(page, { onboardingComplete: true });
  const end = MOCK.QUOTE_ONE.indexOf("know") + 4;
  await page.goto(`/app/chat/${MOCK.CONVERSATION_ID}?m=1&hl=0-${end}`);

  const marked = page.locator("#m-1 mark");
  await expect(marked).toHaveText(MOCK.QUOTE_ONE.slice(0, end));
});

test("the inspect screen shows the evidence, separates what pulls against it, and takes a correction", async ({
  page,
}) => {
  const state = await installApiMock(page, { onboardingComplete: true });
  await page.goto(`/app/recognitions/${MOCK.RECOGNITION_ID}`);

  await expect(page.getByRole("heading", { level: 1 })).toContainText("work things out on the page");
  await expect(page.getByText(/why knori thinks this/i)).toBeVisible();
  // The same sentence is also in the confidence tooltip, which starts hidden.
  await expect(page.getByText(/first impression, not a conclusion/i).last()).toBeVisible();

  // Both supporting quotes, with a day each, and the contradiction kept apart.
  await expect(page.getByText(MOCK.QUOTE_ONE, { exact: false }).first()).toBeVisible();
  await expect(page.getByText(MOCK.QUOTE_TWO, { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: /what pulls against it/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /open in chat/i }).first()).toBeVisible();

  // Correcting it: the sheet refuses an empty answer, then saves.
  await page.getByRole("button", { name: /not quite/i }).click();
  await page.getByRole("button", { name: /save the correction/i }).click();
  await expect(page.getByText(/a sentence is enough/i)).toBeVisible();

  await page.getByRole("button", { name: /not anymore/i }).click();
  await page
    .getByLabel(/what is actually true/i)
    .fill("I decide fast and then write the decision up.");
  await page.getByRole("button", { name: /save the correction/i }).click();

  // What changed: the assertion, the withdrawal, and the profile before/after.
  await expect(page.getByRole("heading", { name: /what your correction changed/i })).toBeVisible();
  await expect(page.getByText(/decides quickly, then writes the decision up/i)).toBeVisible();
  await expect(page.getByText(/1 card built on the old reading/i)).toBeVisible();

  expect(state.feedback).toMatchObject({
    action: "correct",
    reason_code: "outdated",
    correction_text: "I decide fast and then write the decision up.",
  });
});

test("the Recognitions tab explains an empty state instead of looking broken", async ({ page }) => {
  await installApiMock(page, { onboardingComplete: true });
  await page.goto("/app/recognitions");

  // The one-time explainer opens over the first card; it has to be read first.
  await page.getByRole("button", { name: /show me/i }).click();

  await expect(page.getByRole("tab", { name: /^New/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("article").first()).toBeVisible();

  await page.getByRole("tab", { name: /^Accepted/ }).click();
  await expect(page.getByText(/nothing accepted yet/i)).toBeVisible();
});
