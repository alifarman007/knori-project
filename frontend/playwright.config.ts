import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end, against a mocked API (`e2e/mock-api.ts`) — no backend, no keys.
 *
 * The server is the production build rather than `next dev`: the dev server
 * compiles each route on first request, which turns an honest assertion about a
 * redirect into a race with the bundler. `PW_DEV=1` puts the dev server back for
 * quick local iteration.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
  webServer: {
    command: process.env.PW_DEV ? "npm run dev" : "npm run build && npm start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
