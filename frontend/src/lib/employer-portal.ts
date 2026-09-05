/**
 * The employer portal is live.
 *
 * It was retired for a while: the only gate on employer powers was a non-freemail
 * email domain, which made self-serve signup a way for anyone with a bought
 * domain to post straight into the candidate feed, unverified and unwatched.
 *
 * It is back because industries posting their own openings is the point of the
 * academia-industry workflow, and the hole is now closed rather than switched
 * off: an employer may draft and edit freely, but moving a listing to
 * "published" requires a verified careers-page claim - a token placed on the
 * company's own domain. Verification gates reach, not access.
 *
 * Keep this flag and its backend twin (EMPLOYER_PORTAL_ENABLED) in step.
 */
export const EMPLOYER_PORTAL_ENABLED = true;

/** Academician and institution portals, the other two roles problem statement
 *  26044 names. Keep these in step with FACULTY_PORTAL_ENABLED and
 *  INSTITUTION_PORTAL_ENABLED on the backend: a portal reachable in the UI but
 *  gated in the API sends the user to a page that can only fail. */
export const FACULTY_PORTAL_ENABLED = true;
export const INSTITUTION_PORTAL_ENABLED = true;

/** Where an account lands after auth.
 *
 *  Each role routes to its own portal only while that portal is live; anything
 *  disabled, unknown, or absent falls through to the candidate dashboard, which
 *  every account can render. Falling through is deliberate - sending someone to
 *  a portal their account cannot use is a worse failure than showing them the
 *  wrong-but-working page. */
export function landingPathForAccountType(accountType?: string | null): string {
  const normalized = String(accountType ?? "").trim().toLowerCase();
  if (EMPLOYER_PORTAL_ENABLED && normalized === "employer") return "/employer/dashboard";
  if (FACULTY_PORTAL_ENABLED && normalized === "faculty") return "/faculty";
  if (INSTITUTION_PORTAL_ENABLED && normalized === "institution") return "/institution";
  return "/dashboard";
}
