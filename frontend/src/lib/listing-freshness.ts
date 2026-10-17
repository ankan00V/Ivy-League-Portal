/* How long it has been since any source last listed an opening.
 *
 * A listing leaves the feed one of two ways: its deadline passes, or its link
 * stops resolving. Measured on the live corpus, 81% of active listings carry no
 * deadline at all, and 1,347 of 2,587 had not been seen by any scraper in over
 * 30 days - mostly one-off company career-page scrapes that will never run
 * again. A read-only sample of that tail returns 404 or 410 on one link in ten,
 * against none of the listings seen within the last month.
 *
 * So the card has to say something. Sending a student to apply to an opening
 * nothing has confirmed since July, with no hint that this is the case, is the
 * kind of thing they find out only after writing the cover letter.
 *
 * Silent under the threshold: a shorter gap is ordinary scheduling, and a badge
 * on every card teaches people to stop reading badges.
 */
export const STALE_AFTER_DAYS = 30;

export function staleSince(value: string | null | undefined): number | null {
  if (!value) return null;
  const seen = new Date(value).getTime();
  if (Number.isNaN(seen)) return null;
  const days = Math.floor((Date.now() - seen) / 86_400_000);
  return days >= STALE_AFTER_DAYS ? days : null;
}
