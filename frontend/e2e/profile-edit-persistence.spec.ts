import { expect, test, type Route } from "@playwright/test";

test("Profile editing and university selection persist", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("auth_session_present", "1");
    localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
  });

  let storedProfile: Record<string, unknown> = {
    account_type: "candidate",
    first_name: "Initial",
    last_name: "User",
    mobile: "9999999999",
    country_code: "+91",
    user_type: "college_student",
    domain: "Engineering",
    course: "B.Tech",
    passout_year: 2027,
    class_grade: null,
    current_job_role: "",
    total_work_experience: "",
    experience_summary: "",
    college_name: "Unknown Institute",
    company_name: "",
    company_website: "",
    company_size: "",
    company_description: "",
    hiring_for: "",
    goals: [],
    preferred_roles: "",
    preferred_locations: "",
    pan_india: false,
    prefer_wfh: false,
    consent_data_processing: true,
    consent_updates: false,
    bio: "",
    skills: "",
    interests: "",
    achievements: "",
    education: "",
    certificates: "",
    projects: "",
    responsibilities: "",
    gender: "",
    pronouns: "",
    date_of_birth: "",
    current_address_line1: "",
    current_address_landmark: "",
    current_address_region: "",
    current_address_pincode: "",
    permanent_address_line1: "",
    permanent_address_landmark: "",
    permanent_address_region: "",
    permanent_address_pincode: "",
    hobbies: [],
    social_links: {},
    resume_url: "",
    resume_filename: "",
    resume_content_type: "",
    resume_uploaded_at: "",
  };
  let lastSavedPayload: Record<string, unknown> | null = null;

  await page.route("**/api/v1/users/me", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        email: "candidate@example.com",
      }),
    });
  });

  await page.route("**/api/v1/users/me/profile", async (route: Route) => {
    const request = route.request();
    if (request.method() === "PUT") {
      const payload = request.postDataJSON() as Record<string, unknown>;
      lastSavedPayload = payload;
      storedProfile = { ...storedProfile, ...payload };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(storedProfile),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(storedProfile),
    });
  });

  await page.goto("/profile");

  const firstNameInput = page.getByPlaceholder("First name");
  await expect(firstNameInput).toBeVisible();
  await firstNameInput.fill("Edited");
  await expect(firstNameInput).toHaveValue("Edited");
  await page.waitForTimeout(400);
  await expect(firstNameInput).toHaveValue("Edited");

  const universitySelect = page.locator('.profile-field:has-text("College / University") select').first();
  await expect(universitySelect).toBeVisible();
  const selectableUniversityValue = await universitySelect.evaluate((select) => {
    const options = Array.from(select.options);
    const candidate = options.find((option) => option.value && option.value !== "__other__");
    return candidate?.value ?? "";
  });
  expect(selectableUniversityValue).not.toBe("");

  await universitySelect.selectOption(selectableUniversityValue);
  await expect(universitySelect).toHaveValue(selectableUniversityValue);
  await page.waitForTimeout(400);
  await expect(universitySelect).toHaveValue(selectableUniversityValue);
  await expect(page.getByPlaceholder("Type your university name manually")).toHaveCount(0);

  await page.getByRole("button", { name: /^Save$/ }).click();

  await expect.poll(() => lastSavedPayload?.first_name).toBe("Edited");
  await expect.poll(() => lastSavedPayload?.college_name).toBe(selectableUniversityValue);
  await expect(page.getByText("Profile updated successfully.")).toBeVisible();
});
