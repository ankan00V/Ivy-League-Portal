import { expect, test } from "@playwright/test";

test.describe("Browser security headers", () => {
  test("homepage responses include CSP and Trusted Types directives", async ({ request }) => {
    const isProduction = process.env.NODE_ENV === "production";
    const trustedTypesEnabled = process.env.NEXT_PUBLIC_CSP_ENABLE_TRUSTED_TYPES === "1";
    const response = await request.get("/");
    expect(response.ok()).toBeTruthy();
    const headers = response.headers();

    const enforcedCsp = headers["content-security-policy"] || "";
    expect(enforcedCsp).toContain("default-src 'self'");
    if (isProduction && trustedTypesEnabled) {
      expect(enforcedCsp).toContain("require-trusted-types-for 'script'");
      expect(enforcedCsp).toContain("trusted-types");
    } else {
      expect(enforcedCsp).not.toContain("require-trusted-types-for 'script'");
    }
    const scriptDirective = enforcedCsp
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith("script-src "));
    expect(scriptDirective).toBeTruthy();
    expect(scriptDirective || "").not.toContain("'unsafe-inline'");
    expect(scriptDirective || "").not.toContain("'unsafe-eval'");
    expect(enforcedCsp).toContain("https://prod.spline.design");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
  });
});
