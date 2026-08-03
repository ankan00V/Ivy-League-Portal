import { expect, test } from "@playwright/test";

test("@smoke frontend health endpoint is available without backend access", async ({ request }) => {
  const response = await request.get("/api/health");

  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ status: "ok", service: "vidyaverse-frontend" });
});
