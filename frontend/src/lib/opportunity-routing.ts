export type OpportunityPortal = "career" | "competitive" | "other";

export function opportunityPortal(item: {
  portal_category?: string | null;
  opportunity_type?: string | null;
}): OpportunityPortal {
  const portal = item.portal_category?.trim().toLowerCase();
  if (portal === "career" || portal === "competitive" || portal === "other") return portal;
  const kind = item.opportunity_type?.trim().toLowerCase().replace(/s$/, "");
  if (["job", "internship", "hiring challenge"].includes(kind || "")) return "career";
  if (["hackathon", "competition", "conference", "workshop", "webinar", "bootcamp"].includes(kind || "")) return "competitive";
  return "other";
}

export function listingOrganisation(item: { university?: string | null; source?: string | null }): string {
  const name = item.university?.trim();
  const normalized = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!name || ["global", "unknown", "n/a"].includes(name.toLowerCase())) return "Organisation not listed";
  if (item.source && normalized(name) === normalized(item.source)) return "Organisation not listed";
  return name;
}
