import { expect, test, type Page } from "@playwright/test";

type InteractionPayload = {
  opportunity_id: string;
  interaction_type: "impression" | "view" | "click" | "apply" | "save" | "dismiss";
  ranking_mode?: string;
  experiment_key?: string;
  experiment_variant?: string;
  rank_position?: number;
  match_score?: number;
  query?: string | null;
  model_version_id?: string | null;
  features?: Record<string, unknown>;
};

const TEST_OPPORTUNITY = {
  id: "64b64b64b64b64b64b64b64f",
  title: "Test ML Hackathon Bangalore",
  description: "Hands-on buildathon for NLP + RAG systems in Bengaluru.",
  url: "https://example.com/internships/test-ml",
  opportunity_type: "Hackathon",
  portal_category: "competitive",
  university: "Example Labs",
  domain: "AI",
  source: "test_feed",
  ranking_mode: "semantic",
  experiment_key: "ranking_mode",
  experiment_variant: "semantic",
  rank_position: 1,
  match_score: 92.4,
  match_reasons: ["Matches your AI and NLP interests."],
  eligibility_warnings: ["Your graduation year (2026) matches the listed eligible batches."],
  model_version_id: "model-test-v1",
  created_at: "2026-04-16T10:00:00.000Z",
  updated_at: "2026-04-16T10:00:00.000Z",
  last_seen_at: "2026-04-16T10:00:00.000Z",
};

const TEST_CAREER_OPPORTUNITY = {
  ...TEST_OPPORTUNITY,
  id: "75c75c75c75c75c75c75c75f",
  title: "Test ML Internship Bangalore",
  opportunity_type: "Internship",
  portal_category: "career",
};

async function stubOpportunityRoutes(
  page: Page,
  captured: InteractionPayload[],
  opportunities: typeof TEST_OPPORTUNITY[] = [TEST_OPPORTUNITY],
) {
  await page.route("**/api/v1/opportunities/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "GET" && path.includes("/recommended/me")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(opportunities),
      });
      return;
    }

    /* The internships feed pages server-side, so it asks for /page and expects
       an envelope rather than a bare array. Stubbing only the list endpoint left
       paged.items undefined, the grid rendered nothing, and the failure read as
       "the seeded opportunity is missing from the feed" rather than "the stub
       is answering the wrong shape". */
    if (request.method() === "GET" && path.endsWith("/api/v1/opportunities/page")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: opportunities,
          total: opportunities.length,
          page: 1,
          per_page: 12,
          pages: 1,
          facets: {
            tracks: { all: opportunities.length, technical: opportunities.length, non_technical: 0 },
            placements: { all: opportunities.length, india: 0, remote: 0, hybrid: 0, international: 0 },
          },
        }),
      });
      return;
    }

    if (request.method() === "GET" && (path.endsWith("/api/v1/opportunities/") || path.endsWith("/api/v1/opportunities"))) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(opportunities),
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/api/v1/opportunities/interactions/batch")) {
      const body = request.postDataJSON() as { events?: InteractionPayload[] };
      captured.push(...(body.events || []));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/api/v1/opportunities/interactions")) {
      const body = request.postDataJSON() as InteractionPayload;
      captured.push(body);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/api/v1/opportunities/trigger-scraper")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ message: "Scraper job enqueued", job_id: "job-test" }),
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/api/v1/opportunities/ask-ai")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: "ask-ai-req-001",
          query: "best ai internships in bangalore",
          intent: { intent: "internships", confidence: 0.9 },
          entities: { locations: ["bangalore"] },
          results: [
            {
              id: TEST_OPPORTUNITY.id,
              title: TEST_OPPORTUNITY.title,
              url: TEST_OPPORTUNITY.url,
              similarity: 0.94,
            },
          ],
          insights: {
            summary: "Top Bangalore AI internship shortlisted.",
            top_opportunities: [
              {
                opportunity_id: TEST_OPPORTUNITY.id,
                title: TEST_OPPORTUNITY.title,
                why_fit: "Strong NLP + RAG overlap with requested profile.",
                urgency: "high",
                match_score: 94,
                citations: [
                  {
                    opportunity_id: TEST_OPPORTUNITY.id,
                    url: TEST_OPPORTUNITY.url,
                    title: TEST_OPPORTUNITY.title,
                    source: TEST_OPPORTUNITY.source,
                  },
                ],
              },
            ],
            deadline_urgency: "Apply this week.",
            recommended_action: "Apply now.",
            citations: [
              {
                opportunity_id: TEST_OPPORTUNITY.id,
                url: TEST_OPPORTUNITY.url,
                title: TEST_OPPORTUNITY.title,
                source: TEST_OPPORTUNITY.source,
              },
            ],
            safety: {
              hallucination_checks_passed: true,
              failed_checks: [],
              quality_checks_passed: true,
              quality_failed_checks: [],
              judge_score: null,
              judge_rationale: null,
            },
            contract_version: "rag_insights.v1",
          },
        }),
      });
      return;
    }

    if (request.method() === "POST" && path.endsWith("/api/v1/opportunities/ask-ai/feedback")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      });
      return;
    }

    await route.continue();
  });
}

test.describe("Opportunity interaction contracts", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("auth_session_present", "1");
      localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
    });
  });

  test("@smoke logs impression and click metadata from opportunity feed", async ({ page }) => {
    const captured: InteractionPayload[] = [];
    await stubOpportunityRoutes(page, captured);

    await page.goto("/opportunities");
    await expect(page.getByText("Ask for a grounded shortlist")).toBeVisible();

    await expect
      .poll(() =>
        captured.some(
          (event) =>
            event.interaction_type === "impression" &&
            event.ranking_mode === "semantic" &&
            event.experiment_key === "ranking_mode" &&
            event.experiment_variant === "semantic" &&
            Number(event.rank_position) >= 1,
        ),
      )
      .toBeTruthy();

    await page.getByRole("button", { name: /Apply|Join/i }).first().click();

    await expect
      .poll(() =>
        captured.some(
          (event) =>
            event.interaction_type === "click" &&
            event.ranking_mode === "semantic" &&
            event.experiment_key === "ranking_mode" &&
            event.experiment_variant === "semantic" &&
            Number(event.rank_position) >= 1,
        ),
      )
      .toBeTruthy();
  });

  test("@smoke explains a recommendation and logs hide feedback", async ({ page }) => {
    const captured: InteractionPayload[] = [];
    await stubOpportunityRoutes(page, captured);

    await page.goto("/opportunities");
    await expect(page.getByText("Why this matches you")).toBeVisible();
    await expect(page.getByText("Matches your AI and NLP interests.")).toBeVisible();
    await expect(page.getByText("Your graduation year (2026) matches the listed eligible batches.")).toBeVisible();

    await page.getByRole("button", { name: `Hide ${TEST_OPPORTUNITY.title}` }).click();
    await expect(page.getByRole("heading", { name: TEST_OPPORTUNITY.title })).toHaveCount(0);
    await expect.poll(() => captured.some((event) => event.interaction_type === "dismiss")).toBeTruthy();
  });

  test("@smoke keeps matching details and hide feedback in the internships feed", async ({ page }) => {
    const captured: InteractionPayload[] = [];
    await stubOpportunityRoutes(page, captured, [TEST_CAREER_OPPORTUNITY]);

    await page.goto("/internships-jobs");
    await expect(page.getByRole("heading", { name: TEST_CAREER_OPPORTUNITY.title })).toBeVisible();
    await expect(page.getByText("Why this matches you")).toBeVisible();

    await page.getByRole("button", { name: `Hide ${TEST_CAREER_OPPORTUNITY.title}` }).click();
    await expect(page.getByRole("heading", { name: TEST_CAREER_OPPORTUNITY.title })).toHaveCount(0);
    await expect.poll(() => captured.some((event) => event.interaction_type === "dismiss")).toBeTruthy();
  });

  test("events mentioning hiring and engineers remain visible in opportunities", async ({ page }) => {
    const workshop = {
      ...TEST_OPPORTUNITY,
      title: "International AI Workshop for Engineers",
      opportunity_type: "Workshop",
      description: "Meet engineering leaders, explore internships and build AI applications in this workshop.",
    };
    await stubOpportunityRoutes(page, [], [workshop]);
    await page.goto("/opportunities");
    await expect(page.getByRole("heading", { name: workshop.title, exact: true })).toBeVisible();
  });

  test("career cards honor server routing and do not show source names as employers", async ({ page }) => {
    const programme = {
      ...TEST_CAREER_OPPORTUNITY,
      title: "2027 Graduate Programme",
      description: "Participate in workshops and international competitions with your team.",
      source: "example_board",
      university: "Example Board",
    };
    await stubOpportunityRoutes(page, [], [programme]);
    await page.goto("/internships-jobs");
    await expect(page.getByRole("heading", { name: programme.title, exact: true })).toBeVisible();
    await expect(page.getByText("Organisation not listed", { exact: true })).toBeVisible();
  });

  test("opportunities retain recommendation order and collapse repeated ids", async ({ page }) => {
    const first = { ...TEST_OPPORTUNITY, title: "Recommended Python Hackathon", last_seen_at: "2026-01-01T00:00:00Z" };
    const second = { ...TEST_OPPORTUNITY, id: "85c75c75c75c75c75c75c75f", title: "Recent Data Hackathon", last_seen_at: "2026-11-01T00:00:00Z" };
    await stubOpportunityRoutes(page, [], [first, second, first]);
    await page.goto("/opportunities");
    const cards = page.locator("article");
    await expect(cards).toHaveCount(2);
    await expect(cards.first()).toContainText(first.title);
    await expect(cards.last()).toContainText(second.title);
  });

  test("a slow earlier filter response cannot replace the current career feed", async ({ page }) => {
    await stubOpportunityRoutes(page, [], [TEST_CAREER_OPPORTUNITY]);
    let releaseEarlier: () => void = () => {};
    const earlierGate = new Promise<void>((resolve) => { releaseEarlier = resolve; });
    let earlierRequested: () => void = () => {};
    const requestStarted = new Promise<void>((resolve) => { earlierRequested = resolve; });
    await page.route("**/api/v1/opportunities/page?**", async (route) => {
      const track = new URL(route.request().url()).searchParams.get("role_track");
      if (track === "technical") {
        earlierRequested();
        await earlierGate;
      }
      const title = track === "technical" ? "Python Developer Internship" : track === "non_technical" ? "Marketing Internship" : TEST_CAREER_OPPORTUNITY.title;
      await route.fulfill({ json: {
        items: [{ ...TEST_CAREER_OPPORTUNITY, title }], total: 1, pages: 1,
        facets: { tracks: { all: 2, technical: 1, non_technical: 1 }, placements: { all: 1 } },
      } });
    });
    await page.goto("/internships-jobs");
    await expect(page.getByRole("heading", { name: TEST_CAREER_OPPORTUNITY.title, exact: true })).toBeVisible();
    try {
      await page.getByRole("tab", { name: /^Technical/ }).click();
      await requestStarted;
      await page.getByRole("tab", { name: /^Non-technical/i }).click();
      await expect(page.getByRole("heading", { name: "Marketing Internship", exact: true })).toBeVisible();
      const earlierResponse = page.waitForResponse((response) => response.url().includes("role_track=technical"));
      releaseEarlier();
      await earlierResponse;
      await expect(page.getByRole("heading", { name: "Marketing Internship", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Python Developer Internship", exact: true })).toHaveCount(0);
    } finally {
      releaseEarlier();
    }
  });

  test("logs Ask AI impressions and citation clicks with experiment metadata", async ({ page }) => {
    const captured: InteractionPayload[] = [];
    await stubOpportunityRoutes(page, captured);

    await page.goto("/opportunities");
    await expect(page.getByText("Ask for a grounded shortlist")).toBeVisible();

    const input = page.getByLabel("What should the retriever solve?");
    await input.fill("best ai internships in bangalore");
    await page.getByRole("button", { name: "Ask AI" }).click();

    await expect(page.getByText("Top Match")).toBeVisible();

    await expect
      .poll(() =>
        captured.some(
          (event) =>
            event.interaction_type === "impression" &&
            event.experiment_key === "ask_ai_rag" &&
            event.experiment_variant === "semantic" &&
            event.ranking_mode === "semantic" &&
            event.query === "best ai internships in bangalore",
        ),
      )
      .toBeTruthy();

    await page.getByRole("link", { name: TEST_OPPORTUNITY.title }).first().click();

    await expect
      .poll(() =>
        captured.some(
          (event) =>
            event.interaction_type === "click" &&
            event.experiment_key === "ask_ai_rag" &&
            event.experiment_variant === "semantic" &&
            event.ranking_mode === "semantic" &&
            Boolean(event.features?.citation_url),
        ),
      )
      .toBeTruthy();
  });
});
