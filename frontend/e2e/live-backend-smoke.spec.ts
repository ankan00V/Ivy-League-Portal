import { expect, test } from "@playwright/test";

const liveBackendEnabled = process.env.PLAYWRIGHT_LIVE_BACKEND === "1";

test.describe("Live backend smoke", () => {
  test.skip(!liveBackendEnabled, "Set PLAYWRIGHT_LIVE_BACKEND=1 to run integrated smoke checks.");

  test("frontend proxy can reach live opportunities API", async ({ request }) => {
    const response = await request.get("/api/v1/opportunities/?limit=5");
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    expect(Array.isArray(payload)).toBeTruthy();
  });

  test("ask-ai schema remains reachable via proxy", async ({ request }) => {
    const response = await request.get("/api/v1/opportunities/ask-ai/schema");
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    expect(typeof payload).toBe("object");
    expect(payload).toHaveProperty("required");
  });
});
