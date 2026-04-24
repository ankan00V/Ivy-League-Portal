import { expect, test } from "@playwright/test";

const integratedEnabled = process.env.PLAYWRIGHT_INTEGRATED_AUTH === "1";
const adminBearer = process.env.PLAYWRIGHT_STAGING_ADMIN_BEARER || "";
const employerEmail = process.env.PLAYWRIGHT_STAGING_EMPLOYER_EMAIL || "";
const employerPassword = process.env.PLAYWRIGHT_STAGING_EMPLOYER_PASSWORD || "";

function randomEmail(): string {
  const stamp = Date.now();
  const rand = Math.floor(Math.random() * 100000);
  return `e2e_candidate_${stamp}_${rand}@example.test`;
}

test.describe("Staging role and failure paths", () => {
  test.skip(!integratedEnabled, "Set PLAYWRIGHT_INTEGRATED_AUTH=1 to run staging role/failure tests.");

  test("unauthenticated protected APIs return unauthorized", async ({ request }) => {
    const profileRes = await request.get("/api/v1/users/me/profile");
    expect([401, 403]).toContain(profileRes.status());
  });

  test("candidate account cannot access employer dashboard summary", async ({ request }) => {
    const email = randomEmail();
    const password = "Passw0rd!Passw0rd!";

    const registerResponse = await request.post("/api/v1/auth/register", {
      data: {
        email,
        full_name: "Candidate Role Test",
        password,
      },
    });
    expect(registerResponse.ok()).toBeTruthy();

    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);
    const loginResponse = await request.post("/api/v1/auth/login", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      data: body.toString(),
    });
    expect(loginResponse.ok()).toBeTruthy();

    const employerSummaryResponse = await request.get("/api/v1/employer/dashboard/summary");
    expect([401, 403]).toContain(employerSummaryResponse.status());
  });

  test("admin incident endpoints are reachable when admin bearer is configured", async ({ request }) => {
    test.skip(!adminBearer, "Set PLAYWRIGHT_STAGING_ADMIN_BEARER for admin incident path checks.");

    const incidentsResponse = await request.get("/api/v1/mlops/incidents?limit=1", {
      headers: { Authorization: `Bearer ${adminBearer}` },
    });
    expect(incidentsResponse.ok()).toBeTruthy();

    const payload = (await incidentsResponse.json()) as Array<{ id: string }>;
    if (Array.isArray(payload) && payload.length > 0 && payload[0]?.id) {
      const appendTimelineRes = await request.post(`/api/v1/mlops/incidents/${payload[0].id}/timeline`, {
        headers: {
          Authorization: `Bearer ${adminBearer}`,
          "Content-Type": "application/json",
        },
        data: {
          event: "staging_check",
          message: "Automated staging incident API coverage check.",
          payload: { source: "playwright-staging" },
        },
      });
      expect(appendTimelineRes.ok()).toBeTruthy();
    }
  });

  test("employer dashboard summary is reachable when employer credentials are configured", async ({ request }) => {
    test.skip(
      !employerEmail || !employerPassword,
      "Set PLAYWRIGHT_STAGING_EMPLOYER_EMAIL and PLAYWRIGHT_STAGING_EMPLOYER_PASSWORD for employer path checks.",
    );

    const body = new URLSearchParams();
    body.set("username", employerEmail);
    body.set("password", employerPassword);
    const loginResponse = await request.post("/api/v1/auth/login", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      data: body.toString(),
    });
    expect(loginResponse.ok()).toBeTruthy();

    const summaryResponse = await request.get("/api/v1/employer/dashboard/summary");
    expect(summaryResponse.ok()).toBeTruthy();
  });
});
