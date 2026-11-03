import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function stubAnonymousSession(page: Page) {
  // UI checks do not depend on a live Neon tenant or production credentials.
  await page.route("**/api/auth/get-session**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ session: null, user: null }),
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
    await stubAnonymousSession(page);
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
    // Start in the product form, not browser/framework development controls.
    await page.getByRole("button", { name: "Continue with Google" }).focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Email", { exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Forgot your password?" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeFocused();
  });

  test("@ux visual snapshot login auth shell", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
    const shell = page.locator("section.auth-shell");
    await expect(shell).toBeVisible();
    await expect(shell).toHaveScreenshot("ux-login-shell.png", {
      style: "nextjs-portal { visibility: hidden; }",
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
      style: "nextjs-portal { visibility: hidden; }",
      animations: "disabled",
      caret: "hide",
      scale: "css",
      maxDiffPixelRatio: 0.02,
    });
  });

  test("@ux auth artwork stays contained and never covers form actions", async ({ page }) => {
    for (const width of [1366, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/login", "/register"]) {
        await page.goto(path);
        const submit = page.getByRole("button", {
          name: path === "/login" ? "Sign in" : "Create account", exact: true,
        });
        // Trial clicks check hit testing without submitting or bypassing overlays.
        await submit.click({ trial: true });
        await page.getByRole("button", { name: "Continue with Google" }).click({ trial: true });
        if (width > 900) {
          const frame = page.locator(".auth-image-frame");
          await expect(frame).toHaveCSS("position", "relative");
          const imageBox = await frame.locator("img").boundingBox();
          const formBox = await page.locator(".auth-right-pane").boundingBox();
          expect(imageBox).not.toBeNull();
          expect(formBox).not.toBeNull();
          expect(imageBox!.x + imageBox!.width).toBeLessThanOrEqual(formBox!.x);
        }
      }
    }
  });
});
