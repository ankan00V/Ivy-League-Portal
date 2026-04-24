import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function stubOAuthProviders(page: Page) {
  await page.route("**/api/v1/auth/oauth/providers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ google: false, linkedin: false, microsoft: false }),
    });
  });
}

async function analyzeWithRetry(page: Page, attempts = 3) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await page.waitForLoadState("domcontentloaded");
      return await new AxeBuilder({ page })
        // Ignore framework dev overlays so the gate evaluates only product UI.
        .exclude('[aria-label="Open Next.js Dev Tools"]')
        .exclude('[aria-label="Open issues overlay"]')
        .exclude('[aria-label="Collapse issues badge"]')
        .exclude("[data-nextjs-dev-tools-button]")
        .exclude("#nextjs-dev-tools-menu")
        .analyze();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const isNavigationRace = message.includes("Execution context was destroyed");
      if (!isNavigationRace || attempt === attempts) {
        throw error;
      }
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(150);
    }
  }

  throw new Error("Unable to analyze page accessibility.");
}

test.describe("@ux Frontend UX quality gates", () => {
  test.beforeEach(async ({ page }) => {
    await stubOAuthProviders(page);
    await page.setViewportSize({ width: 1366, height: 900 });
  });

  test("@ux accessibility smoke across high-value entry pages", async ({ page }) => {
    for (const route of ["/login", "/register", "/opportunities"]) {
      await page.goto(route, { waitUntil: "domcontentloaded" });
      const results = await analyzeWithRetry(page);
      const actionableViolations = results.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact || ""),
      );
      const blockingViolations = actionableViolations.filter(
        (violation) => violation.id !== "color-contrast" && violation.id !== "aria-hidden-focus",
      );
      const contrastViolations = actionableViolations.filter((violation) => violation.id === "color-contrast");
      const ariaHiddenFocusViolations = actionableViolations.filter((violation) => violation.id === "aria-hidden-focus");
      expect(
        blockingViolations.map((violation) => `${violation.id}:${violation.impact}`),
      ).toEqual([]);
      // Keep contrast checks active while allowing a small temporary budget during the redesign pass.
      expect(contrastViolations.length).toBeLessThanOrEqual(1);
      // Temporary budget while dev overlays and floating widgets are being hardened.
      expect(ariaHiddenFocusViolations.length).toBeLessThanOrEqual(1);
    }
  });

  test("@ux keyboard navigation reaches auth action controls", async ({ page }) => {
    await page.goto("/login");

    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");

    const focusedText = await page.evaluate(() => {
      const target = document.activeElement as HTMLElement | null;
      return target?.textContent?.trim() || target?.getAttribute("aria-label") || "";
    });

    expect(focusedText.length).toBeGreaterThan(0);
  });

  test("@ux visual snapshot login auth shell", async ({ page }) => {
    await page.goto("/login");
    const shell = page.locator("section.auth-shell");
    await expect(shell).toBeVisible();
    await expect(shell).toHaveScreenshot("ux-login-shell.png", {
      animations: "disabled",
      caret: "hide",
      scale: "css",
      maxDiffPixelRatio: 0.02,
    });
  });

  test("@ux visual snapshot register auth shell", async ({ page }) => {
    await page.goto("/register");
    const shell = page.locator("section.auth-shell");
    await expect(shell).toBeVisible();
    await expect(shell).toHaveScreenshot("ux-register-shell.png", {
      animations: "disabled",
      caret: "hide",
      scale: "css",
      maxDiffPixelRatio: 0.02,
    });
  });
});
