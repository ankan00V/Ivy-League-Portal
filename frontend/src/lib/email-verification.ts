/** The address is only a form hint. Verification is always checked by Neon. */
export function verificationCallbackURL(origin: string, email: string): string {
  const url = new URL("/verify-email", origin);
  url.searchParams.set("email", email.trim().toLowerCase());
  url.searchParams.set("returned", "1");
  return url.toString();
}
