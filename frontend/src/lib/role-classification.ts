/**
 * Splits hiring listings into technical and non-technical tracks.
 *
 * The Internships/Jobs feed showed every opening at once, so a commerce student
 * scrolled past backend roles and an engineering student scrolled past sales
 * roles. Both saw a feed that was mostly not for them.
 *
 * The group names come from `role-taxonomy.ts` rather than a second, parallel
 * list, so a role added there is classified here automatically instead of
 * silently falling into "unknown".
 */

import { ROLE_OPTIONS } from "@/lib/role-taxonomy";

export type RoleTrack = "technical" | "non_technical";

const TECHNICAL_GROUPS = new Set([
  "Software Engineering",
  "Data, AI & Research",
  "Infrastructure & Security",
  "Core Engineering",
]);

const NON_TECHNICAL_GROUPS = new Set([
  "Business & Operations",
  "Finance & Accounting",
  "Marketing & Content",
  "Sales & Customer",
  "Law & Policy",
  "Human Resources & Admin",
  "Media & Creative",
  "Education & Social Impact",
]);

/**
 * Keyword chips offered under each track.
 *
 * Each entry carries several terms because one listing says "SDE", another
 * "Software Development Engineer" and a third "Backend Developer". Matching on
 * a single word would quietly hide two of the three.
 */
export type TrackFilter = {
  label: string;
  keywords: string[];
};

export const TECHNICAL_FILTERS: TrackFilter[] = [
  // Language and framework names matter as much as job words. "Python
  // Internship" carries neither "developer" nor "engineer" and was being filed
  // as non-technical until these were added.
  {
    label: "Software",
    keywords: [
      "software", "sde", "developer", "engineer", "full stack", "fullstack",
      "backend", "frontend", "front end", "back end", "web",
      "python", "java", "javascript", "typescript", "react", "angular", "vue",
      "node", "django", "flask", "spring", "golang", "rust", "c++", "c#",
      "php", "ruby", "rails", ".net", "api", "programming", "coding",
    ],
  },
  {
    label: "Data & AI",
    keywords: [
      "data", "machine learning", "ml", "ai", "analytics", "scientist", "nlp",
      "deep learning", "llm", "sql", "pandas", "tensorflow", "pytorch",
      "power bi", "tableau", "statistics", "computer vision", "generative",
    ],
  },
  { label: "Cloud & DevOps", keywords: ["cloud", "devops", "sre", "infrastructure", "platform", "kubernetes", "aws", "azure", "gcp"] },
  { label: "Cybersecurity", keywords: ["security", "cyber", "infosec", "penetration", "soc", "appsec"] },
  { label: "Mobile", keywords: ["mobile", "android", "ios", "flutter", "react native", "swift", "kotlin"] },
  { label: "QA & Testing", keywords: ["qa", "test", "quality assurance", "automation", "sdet"] },
  { label: "Core Engineering", keywords: ["mechanical", "civil", "electrical", "electronics", "chemical", "aerospace", "vlsi", "embedded", "hardware"] },
];

export const NON_TECHNICAL_FILTERS: TrackFilter[] = [
  { label: "Business & Ops", keywords: ["business", "operations", "strategy", "consultant", "consulting", "program", "project manager"] },
  { label: "Finance", keywords: ["finance", "financial", "accounting", "audit", "investment", "banking", "risk", "actuarial", "treasury"] },
  { label: "Marketing", keywords: ["marketing", "seo", "brand", "growth", "digital marketing", "social media", "campaign"] },
  { label: "Sales & Support", keywords: ["sales", "business development", "account executive", "customer success", "customer support", "pre-sales", "bd"] },
  { label: "Product & Design", keywords: ["product manager", "product analyst", "design", "ux", "ui", "graphic", "visual", "figma"] },
  { label: "HR & Admin", keywords: ["human resources", "hr", "recruit", "talent", "people ops", "admin"] },
  { label: "Content & Media", keywords: ["content", "writer", "copywriter", "editor", "journalist", "video", "podcast", "community"] },
  { label: "Legal & Policy", keywords: ["legal", "law", "compliance", "policy", "paralegal", "counsel", "company secretary"] },
];

function buildGroupKeywords(groups: Set<string>): string[] {
  return ROLE_OPTIONS.filter((option) => groups.has(option.group)).map((option) =>
    option.label.toLowerCase(),
  );
}

const TECHNICAL_ROLE_NAMES = buildGroupKeywords(TECHNICAL_GROUPS);
const NON_TECHNICAL_ROLE_NAMES = buildGroupKeywords(NON_TECHNICAL_GROUPS);

const TECHNICAL_HINTS = TECHNICAL_FILTERS.flatMap((filter) => filter.keywords);
const NON_TECHNICAL_HINTS = NON_TECHNICAL_FILTERS.flatMap((filter) => filter.keywords);

function countHits(haystack: string, needles: string[]): number {
  let hits = 0;
  for (const needle of needles) {
    if (haystack.includes(needle)) {
      hits += 1;
    }
  }
  return hits;
}

/**
 * Classify a listing by title, with description and tags as weaker evidence.
 *
 * Scored rather than first-match: "Data Analyst, Marketing" contains both
 * "data" and "marketing", and whichever branch happened to run first would win
 * a first-match rule. Ties resolve to technical only when the title itself
 * carries a technical term, so a generic business listing that merely mentions
 * Excel is not filed as engineering.
 */
export function classifyRoleTrack(input: {
  title?: string | null;
  description?: string | null;
  tags?: string[] | string | null;
  opportunityType?: string | null;
}): RoleTrack {
  const title = String(input.title || "").toLowerCase();
  const tags = Array.isArray(input.tags)
    ? input.tags.join(" ").toLowerCase()
    : String(input.tags || "").toLowerCase();
  const body = `${String(input.description || "").toLowerCase()} ${tags}`;

  // An exact taxonomy role name in the title is the strongest signal available.
  const titleExactTechnical = TECHNICAL_ROLE_NAMES.some((name) => title.includes(name));
  const titleExactNonTechnical = NON_TECHNICAL_ROLE_NAMES.some((name) => title.includes(name));
  if (titleExactTechnical !== titleExactNonTechnical) {
    return titleExactTechnical ? "technical" : "non_technical";
  }

  const technicalScore = countHits(title, TECHNICAL_HINTS) * 3 + countHits(body, TECHNICAL_HINTS);
  const nonTechnicalScore =
    countHits(title, NON_TECHNICAL_HINTS) * 3 + countHits(body, NON_TECHNICAL_HINTS);

  if (technicalScore !== nonTechnicalScore) {
    return technicalScore > nonTechnicalScore ? "technical" : "non_technical";
  }
  // Nothing decisive. Default to non-technical so a mislabelled listing surfaces
  // in the broader track rather than being asserted as engineering.
  return countHits(title, TECHNICAL_HINTS) > 0 ? "technical" : "non_technical";
}

/** True when the listing matches the selected keyword chip. */
export function matchesTrackFilter(
  input: { title?: string | null; description?: string | null; tags?: string[] | string | null },
  filter: TrackFilter | null,
): boolean {
  if (!filter) {
    return true;
  }
  const tags = Array.isArray(input.tags)
    ? input.tags.join(" ").toLowerCase()
    : String(input.tags || "").toLowerCase();
  const haystack = `${String(input.title || "").toLowerCase()} ${String(input.description || "").toLowerCase()} ${tags}`;
  return filter.keywords.some((keyword) => haystack.includes(keyword));
}
