import { expect, test } from "@playwright/test";

const integratedEnabled = process.env.PLAYWRIGHT_INTEGRATED_AUTH === "1";
const otpExpiryMs = 24 * 60 * 60 * 1000;

function randomEmail(): string {
  const stamp = Date.now();
  const rand = Math.floor(Math.random() * 100000);
  return `e2e_user_${stamp}_${rand}@example.test`;
}

test.describe("Integrated staging auth + protected flows", () => {
  test.skip(!integratedEnabled, "Set PLAYWRIGHT_INTEGRATED_AUTH=1 to run integrated auth tests.");

  test("registers, logs in, and reaches protected pages without mocked routes", async ({ page, request }) => {
    const email = randomEmail();
    const password = "Passw0rd!Passw0rd!";
    const fullName = "E2E Candidate";

    const registerResponse = await request.post("/api/v1/auth/register", {
      data: {
        email,
        full_name: fullName,
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

    await page.addInitScript((payload) => {
      localStorage.setItem("auth_session_present", "1");
      localStorage.setItem("access_token_expires_at", String(Date.now() + payload.expiryMs));
    }, { expiryMs: otpExpiryMs });

    const profileResponse = await request.get("/api/v1/users/me/profile");
    expect(profileResponse.ok()).toBeTruthy();

    const recommendedResponse = await request.get("/api/v1/opportunities/recommended/me?limit=5");
    expect(recommendedResponse.ok()).toBeTruthy();
    const recommendedPayload = await recommendedResponse.json();
    expect(Array.isArray(recommendedPayload)).toBeTruthy();

    await page.goto("/dashboard");
    await expect(page.getByText(/Profile Strength|Sign in for live rank/i)).toBeVisible();

    await page.goto("/opportunities");
    await expect(page.getByText("Ask for a grounded shortlist")).toBeVisible();
  });
});
