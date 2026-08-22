/**
 * The employer portal is retired, not deleted.
 *
 * At retirement there were zero employer accounts and zero employer-posted
 * opportunities -- all 2,189 listings came from scrapers -- while the only gate
 * on employer powers was a non-freemail email domain. That made self-serve
 * employer signup a way for anyone with a bought domain to post straight into
 * the candidate feed, with no verification and no one watching.
 *
 * Everything still exists: /employer/dashboard, /employer/applications, and the
 * backend routes. Flip this flag and its backend twin (EMPLOYER_PORTAL_ENABLED)
 * to bring the whole workflow back.
 */
export const EMPLOYER_PORTAL_ENABLED = false;

/** Where an account lands after auth. Employers only route to their own portal
 *  while it is live; otherwise everyone gets the candidate dashboard. */
export function landingPathForAccountType(accountType?: string | null): string {
  const normalized = String(accountType ?? "").trim().toLowerCase();
  return EMPLOYER_PORTAL_ENABLED && normalized === "employer" ? "/employer/dashboard" : "/dashboard";
}
