import { expect, test, type Page } from "@playwright/test";

const EMPLOYER_OPPORTUNITY_ID = "64b64b64b64b64b64b64b640";
const OPPORTUNITY_URL = "https://example.com/internships/test-ml";

async function stubOAuthProviders(page: Page) {
  await page.route("**/api/v1/auth/oauth/providers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ google: false, linkedin: false, microsoft: false }),
    });
  });
}

async function stubTurnstile(page: Page) {
  await page.addInitScript(() => {
    window.turnstile = {
      render: (_container, options) => {
        window.setTimeout(() => options.callback?.("playwright-turnstile-token"), 0);
        return "playwright-widget";
      },
      execute: () => {},
      remove: () => {},
      reset: () => {},
    };
  });
}

test("@smoke login OTP request enforces 60s cooldown in UI", async ({ page }) => {
  await stubOAuthProviders(page);
  await stubTurnstile(page);

  await page.route("**/api/v1/auth/send-otp", async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "retry-after": "60" },
      contentType: "application/json",
      body: JSON.stringify({ message: "OTP sent", cooldown_seconds: 60 }),
    });
  });

  await page.goto("/login");
  await page.getByPlaceholder("Enter Email").fill("student@example.com");
  await page.getByRole("button", { name: /Continue with OTP/i }).click();

  await expect(page.getByPlaceholder("123456")).toBeVisible();
  await expect(page.getByText(/Didn't receive code\?/i)).toBeVisible();
  await expect(page.getByText(/Resend in 0[01]:[0-5]\d/i)).toBeVisible();
});

test("@smoke signup requests OTP with its visible Turnstile token and uses inline resend", async ({ page }) => {
  await stubOAuthProviders(page);
  await stubTurnstile(page);

  let requestBody: Record<string, unknown> | null = null;
  await page.route("**/api/v1/auth/send-otp", async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ message: "OTP sent", cooldown_seconds: 60 }),
    });
  });

  await page.goto("/register");
  await page.getByPlaceholder("Bob").fill("Test");
  await page.getByPlaceholder("Builder").fill("Student");
  await page.getByPlaceholder("student@college.edu").fill("student@lpu.in");
  await page.getByPlaceholder("Create a password").fill("StrongPass1");
  await page.getByPlaceholder("Re-enter password").fill("StrongPass1");
  await page.getByRole("button", { name: "Send OTP", exact: true }).click();

  await expect(page.getByPlaceholder("123456")).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify OTP & Continue", exact: true })).toBeVisible();
  await expect(page.getByText(/Didn't receive code\?/i)).toBeVisible();
  await expect(page.getByText(/Resend in 0[01]:[0-5]\d/i)).toBeVisible();
  expect(requestBody).toMatchObject({
    email: "student@lpu.in",
    purpose: "signup",
    account_type: "candidate",
    turnstile_token: "playwright-turnstile-token",
  });
});

test("signup reports a Turnstile load failure instead of leaving Send OTP pending", async ({ page }) => {
  await stubOAuthProviders(page);
  await page.route("https://challenges.cloudflare.com/**", async (route) => route.abort());

  await page.goto("/register");
  await page.getByPlaceholder("Bob").fill("Test");
  await page.getByPlaceholder("Builder").fill("Student");
  await page.getByPlaceholder("student@college.edu").fill("student@lpu.in");
  await page.getByPlaceholder("Create a password").fill("StrongPass1");
  await page.getByPlaceholder("Re-enter password").fill("StrongPass1");
  await page.getByRole("button", { name: "Send OTP", exact: true }).click();

  await expect(page.getByText("Unable to load Turnstile")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send OTP", exact: true })).toBeEnabled();
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
  await stubOAuthProviders(page);

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
