import { expect, test, type Page } from "@playwright/test";

type InteractionPayload = {
  opportunity_id: string;
  interaction_type: "impression" | "view" | "click" | "apply" | "save";
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
  university: "Example Labs",
  domain: "AI",
  source: "test_feed",
  ranking_mode: "semantic",
  experiment_key: "ranking_mode",
  experiment_variant: "semantic",
  rank_position: 1,
  match_score: 92.4,
  model_version_id: "model-test-v1",
  created_at: "2026-04-16T10:00:00.000Z",
  updated_at: "2026-04-16T10:00:00.000Z",
  last_seen_at: "2026-04-16T10:00:00.000Z",
};

async function stubOpportunityRoutes(page: Page, captured: InteractionPayload[]) {
  await page.route("**/api/v1/opportunities/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (request.method() === "GET" && path.includes("/recommended/me")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TEST_OPPORTUNITY]),
      });
      return;
    }

    if (request.method() === "GET" && (path.endsWith("/api/v1/opportunities/") || path.endsWith("/api/v1/opportunities"))) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([TEST_OPPORTUNITY]),
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
      localStorage.setItem("access_token", "test-token");
      localStorage.setItem("access_token_expires_at", String(Date.now() + 60 * 60 * 1000));
    });
  });

  test("logs impression and click metadata from opportunity feed", async ({ page }) => {
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
