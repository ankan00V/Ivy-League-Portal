import { expect, test, type Page } from "@playwright/test";

const EMPLOYER_OPPORTUNITY_ID = "64b64b64b64b64b64b64b640";
const OPPORTUNITY_URL = "https://example.com/internships/test-ml";

async function stubNeonSignedOut(page: Page) {
  await page.route("**/api/auth/get-session**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: null, session: null }) });
  });
}

test("login and registration links reliably move between account entry screens", async ({ page }) => {
  await stubNeonSignedOut(page);

  await page.goto("/login");
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();

  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("@smoke registration sends a verification link and lands on the recovery-safe verification screen", async ({ page }) => {
  await stubNeonSignedOut(page);
  let requestBody: Record<string, unknown> | null = null;
  await page.route("**/api/auth/sign-up/email", async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { email: "student@gmail.com", emailVerified: false } }) });
  });

  await page.goto("/register");
  await page.getByLabel("Full name").fill("Test Student");
  await page.getByLabel("Email").fill("student@gmail.com");
  await page.getByLabel("Password", { exact: true }).fill("StrongPass1");
  await page.getByLabel("Confirm password").fill("StrongPass1");
  await page.getByRole("button", { name: "Create account", exact: true }).click();

  await expect(page).toHaveURL(/\/verify-email\?email=student%40gmail\.com$/);
  await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Resend verification link" })).toBeVisible();
  expect(requestBody).toMatchObject({
    name: "Test Student",
    email: "student@gmail.com",
    callbackURL: `${new URL(page.url()).origin}/verify-email?email=student%40gmail.com&returned=1`,
  });
});

test("@smoke an incomplete verified account always resumes onboarding instead of falling through to the dashboard", async ({ page }) => {
  await stubNeonSignedOut(page);
  await page.route("**/api/auth/sign-in/email", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "neon-user", email: "student@gmail.com", emailVerified: true } }) });
  });
  await page.route("**/api/auth/bridge", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: "test-token" }) });
  });
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "user-1", is_admin: false }) });
  });
  await page.route("**/api/v1/users/me/profile", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ account_type: "candidate", first_name: "Test", last_name: "Student", country_code: "+91" }) });
  });
  await page.route("**/api/v1/users/me/onboarding-status", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ completed: false, progress_percent: 8, missing_fields: ["mobile"], recommended_next_step: "identity" }) });
  });
  await page.route("**/api/v1/users/me/onboarding/mark-seen", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ onboarding_prompt_seen: true }) });
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill("student@gmail.com");
  await page.getByLabel("Password").fill("StrongPass1");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole("heading", { name: /You.?re almost there/ })).toBeVisible();
  await expect(page.getByText("8% complete")).toBeVisible();
});

test("verification screen resends a link with a safe callback and applies cooldown copy", async ({ page }) => {
  await stubNeonSignedOut(page);
  let requestBody: Record<string, unknown> | null = null;
  await page.route("**/api/auth/send-verification-email", async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: true }) });
  });

  await page.goto("/verify-email?email=student@gmail.com");
  await page.getByRole("button", { name: "Resend verification link" }).click();

  await expect(page.getByText(/A fresh verification link is on its way/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Resend in \d+s/ })).toBeDisabled();
  expect(requestBody).toMatchObject({ email: "student@gmail.com", callbackURL: `${new URL(page.url()).origin}/verify-email?email=student%40gmail.com&returned=1` });
});

test("verification link opened in a new tab continues to prefilled sign-in without claiming a session", async ({ page }) => {
  await stubNeonSignedOut(page);
  await page.goto("/verify-email?email=student%40gmail.com&returned=1");
  await expect(page).toHaveURL(/\/login\?continue=setup&email=student%40gmail.com$/);
  await expect(page.getByLabel("Email")).toHaveValue("student@gmail.com");
  await expect(page.getByText(/Sign in to continue your account setup/)).toBeVisible();
  await expect(page.locator(".auth-message-error")).toHaveCount(0);
});

test("old verification links without tab storage still offer a working continue action", async ({ page }) => {
  await stubNeonSignedOut(page);
  await page.goto("/verify-email");
  await page.getByRole("button", { name: "I verified my email — continue" }).click();
  await expect(page).toHaveURL(/\/login\?continue=setup$/);
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
});

test("expired verification links stay on recovery instead of silently continuing", async ({ page }) => {
  await stubNeonSignedOut(page);
  await page.goto("/verify-email?email=student%40gmail.com&returned=1&error=TOKEN_EXPIRED");
  await expect(page.locator(".auth-message-error")).toContainText("invalid or has expired");
  await expect(page.getByRole("button", { name: "Resend verification link" })).toBeEnabled();
  await expect(page).toHaveURL(/TOKEN_EXPIRED$/);
});

test("verification refresh bypasses the stale cookie cache and never bridges an unverified user", async ({ page }) => {
  let bridgeCalls = 0;
  let freshChecks = 0;
  await page.route("**/api/auth/get-session**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("disableCookieCache") === "true") freshChecks += 1;
    await route.fulfill({ json: { user: { email: "student@gmail.com", emailVerified: false } } });
  });
  await page.route("**/api/auth/bridge", async (route) => {
    bridgeCalls += 1;
    await route.fulfill({ status: 403, json: {} });
  });
  await page.goto("/verify-email?email=student%40gmail.com&returned=1");
  await expect(page.getByText(/Your email is not verified yet/)).toBeVisible();
  expect(freshChecks).toBeGreaterThan(0);
  expect(bridgeCalls).toBe(0);
});

test("password recovery sends a safe reset link and accepts a replacement password", async ({ page }) => {
  await stubNeonSignedOut(page);
  let resetRequest: Record<string, unknown> | null = null;
  let replacementRequest: Record<string, unknown> | null = null;
  await page.route("**/api/auth/request-password-reset", async (route) => {
    resetRequest = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: true }) });
  });
  await page.route("**/api/auth/reset-password", async (route) => {
    replacementRequest = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: true }) });
  });

  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page).toHaveURL(/\/forgot-password$/);
  await page.getByLabel("Email").fill("student@gmail.com");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists for that address/i)).toBeVisible();
  expect(resetRequest).toMatchObject({
    email: "student@gmail.com",
    redirectTo: `${new URL(page.url()).origin}/reset-password`,
  });

  await page.goto("/reset-password?token=single-use-token");
  await page.getByLabel("New password", { exact: true }).fill("StrongPass1");
  await page.getByLabel("Confirm new password", { exact: true }).fill("StrongPass1");
  await page.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByText("Your password has been reset. You can sign in now.")).toBeVisible();
  expect(replacementRequest).toMatchObject({ token: "single-use-token", newPassword: "StrongPass1" });
});

test("a verified managed-auth callback resumes required onboarding even when a dashboard next path is supplied", async ({ page }) => {
  await page.route("**/api/auth/get-session**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: { id: "neon-user", email: "student@gmail.com", emailVerified: true } }),
    });
  });
  await page.route("**/api/auth/bridge", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: "test-token" }) });
  });
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "user-1", is_admin: false }) });
  });
  await page.route("**/api/v1/users/me/profile", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ account_type: "candidate", first_name: "Test", last_name: "Student" }) });
  });
  await page.route("**/api/v1/users/me/onboarding-status", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ completed: false, progress_percent: 8, missing_fields: ["mobile"], recommended_next_step: "identity" }) });
  });
  await page.route("**/api/v1/users/me/onboarding/mark-seen", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ onboarding_prompt_seen: true }) });
  });

  await page.goto("/auth/callback?next=%2Fdashboard");
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole("heading", { name: /You.?re almost there/ })).toBeVisible();
});

test("@smoke unauthenticated users can view dashboard preview without forced login redirect", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem("auth_session_present");
    localStorage.removeItem("access_token");
    localStorage.removeItem("access_token_expires_at");
  });

  await page.goto("/dashboard");

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: /Dashboard Preview/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
});

test("@smoke sidebar logout clears the local session and returns to login", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  await page.route("**/api/v1/users/me/ranking-summary", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rank: 10, total_users: 1000, top_percent: 1 }),
    });
  });
  let logoutRequestCount = 0;
  await page.route("**/api/v1/auth/logout", async (route) => {
    logoutRequestCount += 1;
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/v1/opportunities/**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
  });
  await page.goto("/opportunities");
  await page.getByRole("button", { name: "Logout", exact: true }).first().click();

  await expect(page).toHaveURL(/\/login$/);
  await expect.poll(() => logoutRequestCount).toBe(1);
  await expect
    .poll(() =>
      page.evaluate(() => ({
        marker: localStorage.getItem("auth_session_present"),
        expiry: localStorage.getItem("access_token_expires_at"),
      })),
    )
    .toEqual({ marker: null, expiry: null });
});

test("completed onboarding redirects users away from onboarding page", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  await page.route("**/api/v1/users/me/profile", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        account_type: "candidate",
        first_name: "Test",
        last_name: "User",
      }),
    });
  });

  await page.route("**/api/v1/users/me/onboarding-status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        completed: true,
        progress_percent: 100,
        missing_fields: [],
        recommended_next_step: "done",
      }),
    });
  });

  await page.route("**/api/v1/users/me/ranking-summary", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rank: 10, total_users: 1000, top_percent: 1 }),
    });
  });

  await page.goto("/onboarding");
  await expect.poll(() => page.url()).toContain("/dashboard");
});

test("retired employer dashboard redirects to the candidate dashboard", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  await page.goto("/employer/dashboard");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("apply flow persists application and redirects to opportunity URL", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  const applyRequests: string[] = [];

  await page.route("**/api/v1/opportunities/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === "GET" && url.pathname.includes("/recommended/me")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: EMPLOYER_OPPORTUNITY_ID,
            title: "Applied AI Buildathon",
            description: "Hands-on model training and ranking challenge.",
            url: OPPORTUNITY_URL,
            opportunity_type: "Hackathon",
            university: "Example Labs",
            domain: "AI",
            source: "seed",
            ranking_mode: "semantic",
            experiment_key: "ranking_mode",
            experiment_variant: "semantic",
            rank_position: 1,
            match_score: 91.2,
            model_version_id: "ranker-v2",
            created_at: "2026-04-19T00:00:00.000Z",
            updated_at: "2026-04-19T00:00:00.000Z",
            last_seen_at: "2026-04-19T00:00:00.000Z",
          },
        ]),
      });
      return;
    }

    if (request.method() === "POST" && url.pathname.endsWith("/api/v1/opportunities/interactions")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      });
      return;
    }

    if (request.method() === "POST" && url.pathname.endsWith("/api/v1/opportunities/trigger-scraper")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "queued" }),
      });
      return;
    }

    await route.continue();
  });

  await page.route(`**/api/v1/applications/${EMPLOYER_OPPORTUNITY_ID}*`, async (route) => {
    applyRequests.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ application_id: "app-1", status: "Submitted" }),
    });
  });

  await page.route(OPPORTUNITY_URL, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<html><head><title>Opportunity</title></head><body>Opportunity detail</body></html>",
    });
  });

  await page.goto("/opportunities");
  await page.getByRole("button", { name: /Apply|Join/i }).first().click();

  await expect.poll(() => applyRequests.length).toBeGreaterThan(0);
  const query = new URL(applyRequests[0]).searchParams;
  expect(query.get("ranking_mode")).toBe("semantic");
  expect(query.get("experiment_key")).toBe("ranking_mode");
  expect(query.get("experiment_variant")).toBe("semantic");
  expect(query.get("rank_position")).toBe("1");

  await expect.poll(() => page.url()).toContain(OPPORTUNITY_URL);
});
