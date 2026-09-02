/**
 * The roles someone can sign up or sign in as.
 *
 * Both auth pages previously hardcoded `"candidate" | "employer"` and a
 * two-column toggle, so the two roles added later existed in the API and were
 * unreachable from the interface. The only accounts of those types were ones a
 * seeding script had created, which hid the gap rather than showing it.
 *
 * Keep this list in step with KNOWN_ACCOUNT_TYPES and the *_PORTAL_ENABLED flags
 * on the backend. A role offered here but gated there sends someone through a
 * signup that ends in a refusal; a role enabled there but missing here is one
 * nobody can reach.
 */

import {
  EMPLOYER_PORTAL_ENABLED,
  FACULTY_PORTAL_ENABLED,
  INSTITUTION_PORTAL_ENABLED,
} from "@/lib/employer-portal";

export type AccountType = "candidate" | "employer" | "faculty" | "institution";

export interface AccountRole {
  value: AccountType;
  label: string;
  /** Shown once the role is selected, so the address rule is not a surprise
   *  discovered by being rejected. */
  emailHint: string;
  /** What this account is for, in one line. */
  description: string;
  enabled: boolean;
}

export const ACCOUNT_ROLES: AccountRole[] = [
  {
    value: "candidate",
    label: "Student",
    emailHint: "Sign up with your college email address.",
    description: "Find internships and placements, and see your skill gaps.",
    enabled: true,
  },
  {
    value: "employer",
    label: "Industry",
    emailHint: "Industry sign-up requires a corporate email domain.",
    description: "Post openings and learning programmes, and shortlist applicants.",
    enabled: EMPLOYER_PORTAL_ENABLED,
  },
  {
    value: "faculty",
    label: "Academician",
    emailHint: "Sign up with your institutional email address.",
    description: "Faculty development programmes, fellowships and consultancy.",
    enabled: FACULTY_PORTAL_ENABLED,
  },
  {
    value: "institution",
    label: "Institution",
    emailHint: "Sign up with your institution's email domain.",
    description: "Track your students' skill development and placement progress.",
    enabled: INSTITUTION_PORTAL_ENABLED,
  },
];

export function enabledAccountRoles(): AccountRole[] {
  return ACCOUNT_ROLES.filter((role) => role.enabled);
}

export function accountRole(value: string | null | undefined): AccountRole | undefined {
  const normalized = String(value ?? "").trim().toLowerCase();
  return ACCOUNT_ROLES.find((role) => role.value === normalized);
}
