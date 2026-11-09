import { expect, Page, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function requestCode(page: Page) {
  await page.route("**/api/auth/email-otp/request-password-reset", (route) => route.fulfill({ json: { success: true } }));
  await page.goto("/forgot-password");
  await page.getByLabel("Email", { exact: true }).fill("student@gmail.com");
  await page.getByRole("button", { name: "Send reset code" }).click();
  await expect(page.getByRole("heading", { name: "Enter your reset code" })).toBeVisible();
}

test("wrong, expired, and exhausted codes cannot reach password entry", async ({ page }) => {
  let attempts = 0;
  const codes = ["INVALID_OTP", "OTP_EXPIRED", "TOO_MANY_ATTEMPTS"];
  await page.route("**/api/auth/email-otp/check-verification-otp", (route) => route.fulfill({ status: 400, json: { code: codes[attempts++], message: "Provider internal error" } }));
  await requestCode(page);
  for (const message of ["invalid or has expired", "This code has expired", "Too many incorrect attempts"]) {
    await page.getByLabel("Reset code", { exact: true }).fill("123456");
    await page.getByRole("button", { name: "Verify code" }).click();
    await expect(page.locator("main [role=alert]")).toContainText(message);
    await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Reset code", { exact: true })).toHaveValue("");
  }
  expect(attempts).toBe(3);
});

test("expiry at save returns to code entry and resend enforces cooldown", async ({ page }) => {
  await page.clock.install();
  await page.route("**/api/auth/email-otp/check-verification-otp", (route) => route.fulfill({ json: { success: true } }));
  let saves = 0;
  await page.route("**/api/auth/email-otp/reset-password", (route) => {
    saves++;
    return route.fulfill({ status: 400, json: { code: "OTP_EXPIRED" } });
  });
  await requestCode(page);
  await expect(page.getByRole("button", { name: /Resend code in/ })).toBeDisabled();
  await page.getByLabel("Reset code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Verify code" }).click();
  await page.getByLabel("New password", { exact: true }).fill("StrongPass1");
  await page.getByLabel("Confirm new password", { exact: true }).fill("NotTheSame1");
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page.locator("main [role=alert]")).toContainText("does not match");
  expect(saves).toBe(0);
  await page.getByLabel("Confirm new password", { exact: true }).fill("StrongPass1");
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page.locator("main [role=alert]")).toContainText("This code has expired");
  expect(saves).toBe(1);
  await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
  await page.clock.fastForward(61_000);
  await page.getByRole("button", { name: "Resend code", exact: true }).click();
  await expect(page.locator("main [role=alert]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Resend code in/ })).toBeDisabled();
});

test("network failures stay recoverable and cannot expose account details", async ({ page }) => {
  await page.route("**/api/auth/email-otp/request-password-reset", (route) => route.fulfill({ status: 503, json: { message: "SMTP secret internal error" } }));
  await page.goto("/forgot-password");
  await page.getByLabel("Email", { exact: true }).fill("student@gmail.com");
  await page.getByRole("button", { name: "Send reset code" }).click();
  await expect(page.locator("main [role=alert]")).toContainText("Check your connection");
  await expect(page.locator("main")).not.toContainText("SMTP secret");
  await expect(page.getByRole("button", { name: /Try again in/ })).toBeDisabled();
  await expect(page.getByLabel("Reset code", { exact: true })).toHaveCount(0);
});

test("codes and passwords are not persisted and direct reset URLs cannot skip verification", async ({ page }) => {
  await page.route("**/api/auth/email-otp/check-verification-otp", (route) => route.fulfill({ json: { success: true } }));
  await requestCode(page);
  await page.getByLabel("Reset code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Verify code" }).click();
  await page.getByLabel("New password", { exact: true }).fill("SecretPass1");
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(storage).not.toContain("123456");
  expect(storage).not.toContain("SecretPass1");
  await page.getByRole("button", { name: "Use a different email" }).click();
  await expect(page.getByLabel("Email", { exact: true })).toBeVisible();
  await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
  await page.goto("/reset-password?token=untrusted&verified=true&otp=123456");
  await expect(page.getByLabel("Email", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
});

test("reset screens remain accessible on mobile across all three steps", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/auth/email-otp/check-verification-otp", (route) => route.fulfill({ json: { success: true } }));
  await requestCode(page);
  expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  await page.getByLabel("Reset code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Verify code" }).click();
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeFocused();
  expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
