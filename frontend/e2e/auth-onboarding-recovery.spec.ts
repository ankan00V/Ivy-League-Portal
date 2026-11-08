import { expect, test, type Page } from "@playwright/test";

const user = { id: "recovery-user", email: "student@gmail.com", emailVerified: true };
const profile = {
  account_type: "candidate", first_name: "Test", last_name: "Student",
  mobile: "9876543210", country_code: "+91", user_type: "school_student",
  consent_data_processing: true, onboarding_completed: false,
};
const incomplete = { completed: false, missing_fields: ["class_grade"], progress_percent: 83, recommended_next_step: "class_grade" };

async function appFixtures(page: Page) {
  await page.route("**/api/v1/users/me", (route) => route.fulfill({ json: { id: user.id, is_admin: false } }));
  await page.route("**/api/v1/users/me/profile", (route) => route.fulfill({ json: profile }));
  await page.route("**/api/v1/users/me/onboarding-status", (route) => route.fulfill({ json: incomplete }));
  await page.route("**/api/v1/users/me/onboarding/mark-seen", (route) => route.fulfill({ json: {} }));
}

async function seedAppSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 3_600_000));
  });
}

test("successful sign-in survives a failed app bridge and retries without resubmitting the password", async ({ page }) => {
  let signedIn = false;
  let signIns = 0;
  let bridges = 0;
  await appFixtures(page);
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: signedIn ? { user } : { user: null } }));
  await page.route("**/api/auth/sign-in/email", (route) => {
    signedIn = true;
    signIns++;
    return route.fulfill({ json: { user } });
  });
  await page.route("**/api/auth/bridge", (route) => {
    bridges++;
    return bridges === 1
      ? route.fulfill({ status: 503, json: { detail: "Application service temporarily unavailable." } })
      : route.fulfill({ json: { access_token: "app-test-token" } });
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill("StrongPass1");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("main [role=alert]")).toContainText("temporarily unavailable");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Retry secure sign-in" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Step 2 of 3")).toBeVisible();
  expect(signIns).toBe(1);
  expect(bridges).toBe(2);
});

test("onboarding reload resumes saved details and failed status confirmation never advances the step", async ({ page }) => {
  await seedAppSession(page);
  await appFixtures(page);
  let saves = 0;
  let failConfirmation = false;
  let saved: Record<string, unknown> = {};
  await page.route("**/api/v1/users/me/onboarding", (route) => {
    saves++;
    saved = route.request().postDataJSON();
    return route.fulfill({ json: { ...profile, ...saved } });
  });
  await page.route("**/api/v1/users/me/onboarding-status", (route) => failConfirmation
    ? route.fulfill({ status: 503, json: {} })
    : route.fulfill({ json: saves >= 2 ? { completed: true, missing_fields: [], progress_percent: 100 } : incomplete }));
  await page.goto("/onboarding");
  await expect(page.getByLabel("Step 2 of 3")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Step 2 of 3")).toBeVisible();
  await page.getByRole("button", { name: "10", exact: true }).click();
  failConfirmation = true;
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator("main [role=alert]")).toContainText("details were saved");
  await expect(page.getByLabel("Step 2 of 3")).toBeVisible();
  expect(saved).toMatchObject({ first_name: "Test", mobile: "9876543210", class_grade: 10 });
  failConfirmation = false;
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Step 3 of 3")).toBeVisible();
  await page.getByRole("button", { name: "Finish", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect(saves).toBe(3);
});

test("an expired application session restores managed auth instead of signing the user out", async ({ page }) => {
  await seedAppSession(page);
  await appFixtures(page);
  let profileReads = 0;
  let signOuts = 0;
  await page.route("**/api/v1/users/me/profile", (route) => ++profileReads === 1
    ? route.fulfill({ status: 401, json: {} }) : route.fulfill({ json: profile }));
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: { user } }));
  await page.route("**/api/auth/bridge", (route) => route.fulfill({ json: { access_token: "fresh-test-token" } }));
  await page.route("**/api/auth/sign-out", (route) => { signOuts++; return route.fulfill({ json: {} }); });
  await page.goto("/onboarding");
  await expect(page.getByLabel("Step 2 of 3")).toBeVisible();
  expect(profileReads).toBeGreaterThan(1);
  expect(signOuts).toBe(0);
});

test("verification for another email cannot silently continue with the signed-in account", async ({ page }) => {
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: { user } }));
  let bridges = 0;
  await page.route("**/api/auth/bridge", (route) => { bridges++; return route.fulfill({ json: {} }); });
  await page.goto("/verify-email?email=another%40gmail.com&returned=1");
  await expect(page.locator("main [role=alert]")).toContainText("different account");
  expect(bridges).toBe(0);
});

test("old password reset links start code recovery instead of accepting URL tokens", async ({ page }) => {
  await page.goto("/reset-password?error=INVALID_TOKEN");
  await expect(page.getByLabel("Email", { exact: true })).toBeVisible();
  await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send reset code" })).toBeVisible();
});

test("resume upload and removal preserve unsaved profile details and clear removed file state", async ({ page }) => {
  await seedAppSession(page);
  await appFixtures(page);
  const persisted = { ...profile, user_type: "professional", current_job_role: "Old role", total_work_experience: "" };
  await page.route("**/api/v1/users/me/profile", (route) => route.fulfill({ json: persisted }));
  await page.route("**/api/v1/users/me/onboarding-status", (route) => route.fulfill({ json: { ...incomplete, missing_fields: ["resume", "current_job_role"] } }));
  let uploads = 0;
  await page.route("**/api/v1/users/me/resume", (route) => {
    const uploading = route.request().method() === "POST";
    if (uploading) uploads++;
    return route.fulfill({ json: {
      ...persisted, resume_url: uploading ? "/api/v1/users/me/resume/download" : null,
      resume_filename: uploading ? "resume.txt" : null, resume_uploaded_at: null,
    } });
  });
  await page.goto("/onboarding");
  const role = page.getByPlaceholder("Software Engineer / Analyst ...");
  await role.fill("My new role");
  await page.locator("input[type=file]").setInputFiles({ name: "invalid.exe", mimeType: "application/octet-stream", buffer: Buffer.from("invalid") });
  await expect(page.locator("main [role=alert]")).toContainText("up to 8 MB");
  expect(uploads).toBe(0);
  await page.locator("input[type=file]").setInputFiles({ name: "resume.txt", mimeType: "text/plain", buffer: Buffer.from("Test resume") });
  await expect(page.getByText("Uploaded: resume.txt", { exact: true })).toBeVisible();
  await expect(role).toHaveValue("My new role");
  await page.getByRole("button", { name: "Remove Resume" }).click();
  await expect(page.getByText("Resume not uploaded yet.")).toBeVisible();
  await expect(role).toHaveValue("My new role");
});
