import { defineConfig, devices } from "@playwright/test";

const stagingBaseUrl = process.env.PLAYWRIGHT_STAGING_URL;
const isStagingMode = Boolean(stagingBaseUrl);
const useSystemChrome = process.env.PLAYWRIGHT_USE_SYSTEM_CHROME === "1";
// Port 3000 is the most contended port on any dev machine, and reuseExistingServer
// is on outside CI - so whatever already holds 3000 gets tested instead of this
// app, silently. That is how a snapshot run ends up screenshotting someone else's
// project. Overridable so a local run can move out of the way.
const devPort = process.env.PLAYWRIGHT_PORT || "3000";
const devUrl = `http://127.0.0.1:${devPort}`;

export default defineConfig({
  testDir: "./e2e",
  snapshotPathTemplate: "{testDir}/{testFilePath}-snapshots/{arg}-{projectName}{ext}",
  fullyParallel: true,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || stagingBaseUrl || devUrl,
    trace: "retain-on-failure",
  },
  webServer: isStagingMode
    ? undefined
    : {
        command: `npm run dev -- --hostname 127.0.0.1 --port ${devPort}`,
        cwd: __dirname,
        url: devUrl,
        env: {
          // Exercise the visible Turnstile branch without putting a production
          // site key in CI. Individual tests replace the widget implementation.
          NEXT_PUBLIC_TURNSTILE_SITE_KEY:
            process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "1x00000000000000000000AA",
        },
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: useSystemChrome ? "chrome" : undefined },
    },
  ],
});
