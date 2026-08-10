import { expect, test, type Route } from "@playwright/test";

test("@smoke profile editing and university selection persist", async ({ page }) => {
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
    expected_stipend_range: "",
    availability: "",
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
    current_address_region: "",
    permanent_address_region: "",
    hobbies: [],
    social_links: {},
    resume_url: "/api/v1/users/me/resume/download",
    resume_filename: "candidate-resume.pdf",
    resume_content_type: "application/pdf",
    resume_uploaded_at: "2026-08-02T00:00:00.000Z",
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

  await page.route("**/api/v1/users/me/resume/review", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        version: "resume_readiness.v1",
        resume_filename: "candidate-resume.pdf",
        score: 78,
        summary: "Strong resume readiness signals are present.",
        categories: [
          {
            key: "skills",
            label: "Skills evidence",
            score: 16,
            maximum: 20,
            evidence: ["Dedicated skills section found", "Detected technical skills: python, sql"],
          },
        ],
        strengths: ["Skills evidence"],
        weaknesses: ["Measured impact"],
        recommendations: ["Add outcome-focused bullets with metrics, scale, or time saved"],
        advisory: "This review measures clarity and ATS readability only. It does not predict hiring outcomes or make eligibility decisions.",
      }),
    });
  });

  await page.goto("/profile");

  const firstNameInput = page.getByPlaceholder("First name");
  await expect(firstNameInput).toBeVisible();
  await firstNameInput.fill("edited");
  await expect(firstNameInput).toHaveValue("EDITED");
  await page.waitForTimeout(400);
  await expect(firstNameInput).toHaveValue("EDITED");

  const universitySelect = page.locator('.profile-field:has-text("College / University") select').first();
  await expect(universitySelect).toBeVisible();
  const selectableUniversityValue = await universitySelect.evaluate((element) => {
    const select = element as HTMLSelectElement;
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

  await page.getByPlaceholder("₹20,000–₹35,000 per month").fill("₹20,000–₹35,000 per month");
  await page.locator('.profile-field:has-text("Availability") select').selectOption("within_1_month");

  await page.getByRole("button", { name: /^Save$/ }).click();

  await expect.poll(() => lastSavedPayload?.first_name).toBe("EDITED");
  await expect.poll(() => lastSavedPayload?.college_name).toBe(selectableUniversityValue.toLocaleUpperCase("en-IN"));
  await expect.poll(() => lastSavedPayload?.expected_stipend_range).toBe("₹20,000–₹35,000 per month");
  await expect.poll(() => lastSavedPayload?.availability).toBe("within_1_month");
  await expect(page.getByText("Profile updated successfully.")).toBeVisible();

  await page.getByRole("button", { name: /Resume/ }).click();
  await expect(page.getByRole("heading", { name: "Resume Readiness Review" })).toBeVisible();
  await expect(page.getByText("78/100")).toBeVisible();
  await expect(page.getByText("Add outcome-focused bullets with metrics, scale, or time saved")).toBeVisible();
});
