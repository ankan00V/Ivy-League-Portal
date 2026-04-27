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

test("login OTP request enforces 60s cooldown in UI", async ({ page }) => {
  await stubOAuthProviders(page);

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
  await expect(page.getByRole("button", { name: /Resend OTP in (59|60)s/i })).toBeVisible();
});

test("unauthenticated users can view dashboard preview without forced login redirect", async ({ page }) => {
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

test("employer lifecycle update posts expected transition", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  let lifecycleStatus = "draft";
  const capturedStatuses: string[] = [];

  await page.route("**/api/v1/users/me/profile", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ account_type: "employer", first_name: "Ankan", company_name: "VidyaVerse" }),
    });
  });

  await page.route("**/api/v1/employer/dashboard/summary", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        company_name: "VidyaVerse",
        opportunities_posted: 1,
        active_opportunities: lifecycleStatus === "published" ? 1 : 0,
        total_applications: 0,
        submitted_applications: 0,
        pending_applications: 0,
        auto_filled_applications: 0,
        shortlisted_applications: 0,
        rejected_applications: 0,
        interview_applications: 0,
        recent_applications: [],
      }),
    });
  });

  await page.route("**/api/v1/employer/opportunities", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: EMPLOYER_OPPORTUNITY_ID,
          title: "Campus AI Internship",
          description: "Build retrieval and ranking systems.",
          opportunity_type: "Internship",
          domain: "AI",
          location: "Bengaluru",
          eligibility: "CS students",
          application_url: OPPORTUNITY_URL,
          deadline: "2026-05-01T00:00:00.000Z",
          lifecycle_status: lifecycleStatus,
          applications_count: 0,
          created_at: "2026-04-19T00:00:00.000Z",
        },
      ]),
    });
  });

  await page.route("**/api/v1/employer/audit-logs?limit=25", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route(`**/api/v1/employer/opportunities/${EMPLOYER_OPPORTUNITY_ID}/lifecycle`, async (route) => {
    const payload = route.request().postDataJSON() as { status?: string };
    const nextStatus = String(payload.status || "draft");
    capturedStatuses.push(nextStatus);
    lifecycleStatus = nextStatus;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: EMPLOYER_OPPORTUNITY_ID,
        title: "Campus AI Internship",
        description: "Build retrieval and ranking systems.",
        opportunity_type: "Internship",
        domain: "AI",
        location: "Bengaluru",
        eligibility: "CS students",
        application_url: OPPORTUNITY_URL,
        deadline: "2026-05-01T00:00:00.000Z",
        lifecycle_status: lifecycleStatus,
        applications_count: 0,
        created_at: "2026-04-19T00:00:00.000Z",
      }),
    });
  });

  await page.goto("/employer/dashboard");
  await expect(page.getByText("Employer Command Center")).toBeVisible();

  const lifecycleSelect = page.locator('section:has-text("Your Posted Opportunities") table tbody tr select').first();
  await lifecycleSelect.selectOption("published");

  await expect
    .poll(() => capturedStatuses.includes("published"))
    .toBeTruthy();
  await expect(page.getByText("Lifecycle updated to published.")).toBeVisible();
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
