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
  /** Placeholder for the email field, so the example address matches the rule. */
  emailPlaceholder: string;
  /** What the two name fields are collecting. For an institution the account
   *  holder is the organisation, so these name the person operating it. */
  nameLabel: { first: string; last: string; firstPlaceholder: string; lastPlaceholder: string };
  /** The line under the sign-up heading. "Unlock personalized recommendations"
   *  is a promise made to students; the other three roles are not getting
   *  recommendations and should not be told they are. */
  signupPromise: string;
  enabled: boolean;
}

export const ACCOUNT_ROLES: AccountRole[] = [
  {
    value: "candidate",
    label: "Student",
    emailHint: "Sign up with your college email address.",
    description: "Find internships and placements, and see your skill gaps.",
    emailPlaceholder: "student@college.edu",
    nameLabel: { first: "First Name", last: "Last Name", firstPlaceholder: "Bob", lastPlaceholder: "Builder" },
    signupPromise: "Verify with OTP and complete a guided profile setup to unlock personalised recommendations.",
    enabled: true,
  },
  {
    value: "employer",
    label: "Industry",
    emailHint: "Industry sign-up requires a corporate email domain.",
    description: "Post openings and learning programmes, and shortlist applicants.",
    emailPlaceholder: "name@company.com",
    nameLabel: { first: "First Name", last: "Last Name", firstPlaceholder: "Recruiter", lastPlaceholder: "Name" },
    signupPromise: "Verify with OTP, then add your company details to post openings and learning programmes.",
    enabled: EMPLOYER_PORTAL_ENABLED,
  },
  {
    value: "faculty",
    label: "Academician",
    emailHint: "Sign up with your institutional email address.",
    description: "Faculty development programmes, fellowships and consultancy.",
    emailPlaceholder: "you@institution.ac.in",
    nameLabel: { first: "First Name", last: "Last Name", firstPlaceholder: "Faculty", lastPlaceholder: "Name" },
    signupPromise: "Verify with OTP, then add your department and designation to see programmes meant for academicians.",
    enabled: FACULTY_PORTAL_ENABLED,
  },
  {
    value: "institution",
    label: "Institution",
    emailHint: "Sign up with your institution's email domain.",
    description: "Track your students' skill development and placement progress.",
    emailPlaceholder: "office@institution.ac.in",
    nameLabel: { first: "Contact First Name", last: "Contact Last Name", firstPlaceholder: "Registrar", lastPlaceholder: "Name" },
    signupPromise: "Verify with OTP, then add your institution details and AISHE code to see your cohort.",
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
