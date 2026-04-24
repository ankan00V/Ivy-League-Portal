import { defineConfig, devices } from "@playwright/test";

const stagingBaseUrl = process.env.PLAYWRIGHT_STAGING_URL;
const isStagingMode = Boolean(stagingBaseUrl);

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
    baseURL: process.env.PLAYWRIGHT_BASE_URL || stagingBaseUrl || "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  webServer: isStagingMode
    ? undefined
    : {
        command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
        cwd: __dirname,
        url: "http://127.0.0.1:3000",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
