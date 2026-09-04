"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Award,
  BriefcaseBusiness,
  CheckCircle2,
  Circle,
  Download,
  FileText,
  GraduationCap,
  Link2,
  MapPinned,
  NotebookPen,
  Save,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  Workflow,
  X,
} from "lucide-react";

import { CenteredPageSkeleton } from "@/components/LoadingSkeletons";
import BackupEmailPanel from "@/components/BackupEmailPanel";
import DeleteAccountPanel from "@/components/DeleteAccountPanel";
import Sidebar from "@/components/Sidebar";
import ResumeReadinessReview from "@/components/ResumeReadinessReview";
import SkillAutocompleteInput from "@/components/skills/SkillAutocompleteInput";
import FormSection from "@/components/ui/FormSection";
import PillGroup from "@/components/ui/PillGroup";
import SelectField from "@/components/ui/SelectField";
import TextareaField from "@/components/ui/TextareaField";
import TextField from "@/components/ui/TextField";
import TaxonomyMultiSelect from "@/components/ui/TaxonomyMultiSelect";
import ToggleRow from "@/components/ui/ToggleRow";
import { useProfileData } from "@/hooks/useProfileData";
import { landingPathForAccountType } from "@/lib/employer-portal";
import { accountRole, type AccountType } from "@/lib/account-roles";
import { INDIAN_INSTITUTION_OPTIONS, OTHER_INSTITUTION_LABEL } from "@/lib/indian-institutions";
import {
  EDUCATION_PROGRAM_GROUPS,
  EDUCATION_PROGRAM_OPTIONS,
  getFieldOfStudyOptions,
} from "@/lib/education-taxonomy";
import { ROLE_GROUPS, ROLE_OPTIONS, findKnownRole, joinRoles, splitRoles } from "@/lib/role-taxonomy";
import {
  LOCATION_GROUPS,
  LOCATION_OPTIONS,
  joinLocations,
  splitLocations,
} from "@/lib/location-taxonomy";

type UserType = "school_student" | "college_student" | "fresher" | "professional";

type SectionKey =
  | "basic"
  | "resume"
  | "about"
  | "skills"
  | "education"
  | "work"
  | "accomplishments"
  | "personal"
  | "social";

/** One education entry. Mirrors backend EducationEntry (models/profile.py). */
type EducationEntryValue = {
  school: string;
  degree: string;
  field_of_study: string;
  start_month: number | null;
  start_year: number | null;
  end_month: number | null;
  end_year: number | null;
  grade: string;
  activities: string;
  description: string;
  skills: string[];
};

const EMPTY_EDUCATION_ENTRY: EducationEntryValue = {
  school: "",
  degree: "",
  field_of_study: "",
  start_month: null,
  start_year: null,
  end_month: null,
  end_year: null,
  grade: "",
  activities: "",
  description: "",
  skills: [],
};

const MONTH_OPTIONS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Wide enough for a school start and an expected graduation a few years out.
const YEAR_OPTIONS = (() => {
  const now = new Date().getFullYear();
  const years: number[] = [];
  for (let year = now + 8; year >= now - 60; year -= 1) {
    years.push(year);
  }
  return years;
})();

function hydrateEducationEntries(raw: unknown): EducationEntryValue[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      school: toText(row.school),
      degree: toText(row.degree),
      field_of_study: toText(row.field_of_study),
      start_month: toNullableNumber(row.start_month),
      start_year: toNullableNumber(row.start_year),
      end_month: toNullableNumber(row.end_month),
      end_year: toNullableNumber(row.end_year),
      grade: toText(row.grade),
      activities: toText(row.activities),
      description: toText(row.description),
      skills: Array.isArray(row.skills) ? row.skills.map((s) => toText(s)).filter(Boolean) : [],
    };
  });
}

/** Accomplishment entries. Mirror the backend models in models/profile.py. */
type ProjectEntryValue = {
  name: string; description: string; url: string; is_current: boolean;
  start_month: number | null; start_year: number | null;
  end_month: number | null; end_year: number | null; skills: string[];
};
type CertificationEntryValue = {
  name: string; issuing_organization: string;
  issue_month: number | null; issue_year: number | null;
  expiry_month: number | null; expiry_year: number | null;
  credential_id: string; credential_url: string; skills: string[];
};
type HonorEntryValue = {
  title: string; issuer: string;
  issue_month: number | null; issue_year: number | null; description: string;
};
type VolunteerEntryValue = {
  organization: string; role: string; cause: string; is_current: boolean;
  start_month: number | null; start_year: number | null;
  end_month: number | null; end_year: number | null; description: string;
};

const EMPTY_PROJECT_ENTRY: ProjectEntryValue = {
  name: "", description: "", url: "", is_current: false,
  start_month: null, start_year: null, end_month: null, end_year: null, skills: [],
};
const EMPTY_CERTIFICATION_ENTRY: CertificationEntryValue = {
  name: "", issuing_organization: "", issue_month: null, issue_year: null,
  expiry_month: null, expiry_year: null, credential_id: "", credential_url: "", skills: [],
};
const EMPTY_HONOR_ENTRY: HonorEntryValue = {
  title: "", issuer: "", issue_month: null, issue_year: null, description: "",
};
const EMPTY_VOLUNTEER_ENTRY: VolunteerEntryValue = {
  organization: "", role: "", cause: "", is_current: false,
  start_month: null, start_year: null, end_month: null, end_year: null, description: "",
};

function toSkillList(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.map((s) => toText(s)).filter(Boolean) : [];
}

function hydrateProjectEntries(raw: unknown): ProjectEntryValue[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      name: toText(row.name), description: toText(row.description), url: toText(row.url),
      is_current: Boolean(row.is_current),
      start_month: toNullableNumber(row.start_month), start_year: toNullableNumber(row.start_year),
      end_month: toNullableNumber(row.end_month), end_year: toNullableNumber(row.end_year),
      skills: toSkillList(row.skills),
    };
  });
}

function hydrateCertificationEntries(raw: unknown): CertificationEntryValue[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      name: toText(row.name), issuing_organization: toText(row.issuing_organization),
      issue_month: toNullableNumber(row.issue_month), issue_year: toNullableNumber(row.issue_year),
      expiry_month: toNullableNumber(row.expiry_month), expiry_year: toNullableNumber(row.expiry_year),
      credential_id: toText(row.credential_id), credential_url: toText(row.credential_url),
      skills: toSkillList(row.skills),
    };
  });
}

function hydrateHonorEntries(raw: unknown): HonorEntryValue[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      title: toText(row.title), issuer: toText(row.issuer),
      issue_month: toNullableNumber(row.issue_month), issue_year: toNullableNumber(row.issue_year),
      description: toText(row.description),
    };
  });
}

function hydrateVolunteerEntries(raw: unknown): VolunteerEntryValue[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      organization: toText(row.organization), role: toText(row.role), cause: toText(row.cause),
      is_current: Boolean(row.is_current),
      start_month: toNullableNumber(row.start_month), start_year: toNullableNumber(row.start_year),
      end_month: toNullableNumber(row.end_month), end_year: toNullableNumber(row.end_year),
      description: toText(row.description),
    };
  });
}

type ExperienceEntryValue = {
  title: string; organization: string; location: string;
  location_type: string; employment_type: string; is_current: boolean;
  start_month: number | null; start_year: number | null;
  end_month: number | null; end_year: number | null;
  highlights: string; skills: string[];
};

const EMPTY_EXPERIENCE_ENTRY: ExperienceEntryValue = {
  title: "", organization: "", location: "", location_type: "", employment_type: "",
  is_current: false, start_month: null, start_year: null,
  end_month: null, end_year: null, highlights: "", skills: [],
};

const EMPLOYMENT_TYPES: [string, string][] = [
  ["full_time", "Full-time"], ["part_time", "Part-time"], ["internship", "Internship"],
  ["freelance", "Freelance"], ["contract", "Contract"], ["apprenticeship", "Apprenticeship"],
  ["seasonal", "Seasonal"],
];

const LOCATION_TYPES: [string, string][] = [
  ["on_site", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"],
];

function hydrateExperienceEntries(raw: unknown): ExperienceEntryValue[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = (item || {}) as Record<string, unknown>;
    return {
      title: toText(row.title), organization: toText(row.organization),
      location: toText(row.location), location_type: toText(row.location_type),
      employment_type: toText(row.employment_type), is_current: Boolean(row.is_current),
      start_month: toNullableNumber(row.start_month), start_year: toNullableNumber(row.start_year),
      end_month: toNullableNumber(row.end_month), end_year: toNullableNumber(row.end_year),
      highlights: toText(row.highlights), skills: toSkillList(row.skills),
    };
  });
}

type ProfilePayload = {
  account_type: AccountType;
  first_name: string;
  last_name: string;
  mobile: string;
  country_code: string;
  user_type: UserType | "";
  domain: string;
  course: string;
  course_specialization: string;
  passout_year: number | null;
  class_grade: number | null;
  current_job_role: string;
  total_work_experience: string;
  experience_summary: string;
  college_name: string;
  company_name: string;
  company_website: string;
  company_size: string;
  company_description: string;
  hiring_for: "myself" | "others" | "";
  goals: string[];
  career_intent: string[];
  preferred_roles: string;
  preferred_locations: string;
  work_preferences: string[];
  expected_stipend_range: string;
  availability: string;
  pan_india: boolean;
  prefer_wfh: boolean;
  consent_data_processing: boolean;
  consent_updates: boolean;
  bio: string;
  skills: string;
  interests: string;
  interest_graph: string[];
  achievements: string;
  education: string;
  education_entries: EducationEntryValue[];
  experience_entries: ExperienceEntryValue[];
  project_entries: ProjectEntryValue[];
  certification_entries: CertificationEntryValue[];
  honor_entries: HonorEntryValue[];
  volunteer_entries: VolunteerEntryValue[];
  certificates: string;
  projects: string;
  responsibilities: string;
  current_address_region: string;
  permanent_address_region: string;
  hobbies: string[];
  social_links: Record<string, string>;
  resume_url: string;
  resume_filename: string;
  resume_content_type: string;
  resume_uploaded_at: string;
};

type ProfileUpdatePayload = {
  account_type: AccountType;
  first_name?: string;
  last_name?: string;
  mobile?: string;
  country_code?: string;
  user_type?: UserType;
  domain?: string;
  course?: string;
  course_specialization?: string;
  passout_year?: number | null;
  class_grade?: number | null;
  current_job_role?: string;
  total_work_experience?: string;
  experience_summary?: string;
  college_name?: string;
  company_name?: string;
  company_website?: string;
  company_size?: string;
  company_description?: string;
  hiring_for?: "myself" | "others";
  goals?: string[];
  career_intent?: string[];
  preferred_roles?: string;
  preferred_locations?: string;
  work_preferences?: string[];
  expected_stipend_range?: string;
  availability?: string;
  pan_india: boolean;
  prefer_wfh: boolean;
  consent_data_processing: boolean;
  consent_updates: boolean;
  bio?: string;
  skills?: string;
  interests?: string;
  interest_graph?: string[];
  achievements?: string;
  education?: string;
  education_entries?: EducationEntryValue[];
  experience_entries?: ExperienceEntryValue[];
  project_entries?: ProjectEntryValue[];
  certification_entries?: CertificationEntryValue[];
  honor_entries?: HonorEntryValue[];
  volunteer_entries?: VolunteerEntryValue[];
  certificates?: string;
  projects?: string;
  responsibilities?: string;
  current_address_region?: string;
  permanent_address_region?: string;
  hobbies?: string[];
  social_links?: Record<string, string>;
};

type SectionMeta = {
  key: SectionKey;
  label: string;
  description: string;
  icon: LucideIcon;
  requiredCandidate?: boolean;
  requiredEmployer?: boolean;
  /** Which roles this section applies to. Every section used to render for
   *  every role, so an industry recruiter was asked to upload a CV and an
   *  institution was asked for its degree - the `required` flags marked
   *  sections mandatory but never hid the ones that made no sense. */
  roles: AccountType[];
};

const USER_TYPE_OPTIONS: Array<{ key: UserType; label: string }> = [
  { key: "college_student", label: "College Student" },
  { key: "professional", label: "Professional" },
  { key: "school_student", label: "School Student" },
  { key: "fresher", label: "Fresher" },
];

const DOMAIN_OPTIONS = ["Engineering", "Management", "Arts & Science", "Medicine", "Law", "Other"];
const GOAL_OPTIONS = ["To find a Job", "Compete & Upskill", "To Host an Event", "To be a Mentor"];
const OTHER_UNIVERSITY_VALUE = "__other__";
const OTHER_COURSE_VALUE = "__other_course__";
const OTHER_SPECIALIZATION_VALUE = "__other_specialization__";
const OTHER_ROLE_VALUE = "__other_role__";
const UNIVERSITY_OPTION_VALUES = new Set<string>(INDIAN_INSTITUTION_OPTIONS.map((item) => item.label));
const UNIVERSITY_OPTIONS = Array.from(UNIVERSITY_OPTION_VALUES);
const UNIVERSITY_OPTION_BY_UPPERCASE = new Map<string, string>(
  UNIVERSITY_OPTIONS.map((item) => [item.toLocaleUpperCase("en-IN"), item]),
);

/* Free-text fields that get shouted for visual consistency.
   Taxonomy-backed fields are deliberately NOT in here. Uppercasing them broke
   every control that compares a stored value against a canonical option:
   a Domain pill compared "ENGINEERING" against "Engineering" and never lit up,
   and a <select> holding "B.TECH (BACHELOR OF TECHNOLOGY)" matched no <option
   value> and rendered blank. Those fields now store the canonical label, and
   the display-uppercasing is done in CSS where it belongs. */
const UPPERCASE_TEXT_FIELDS = new Set<keyof ProfilePayload>([
  "first_name",
  "last_name",
  "total_work_experience",
  "experience_summary",
  "college_name",
  "company_name",
  "company_size",
  "company_description",
  "bio",
  "achievements",
  "education",
  "certificates",
  "projects",
  "responsibilities",
  "current_address_region",
  "permanent_address_region",
]);

const SOCIAL_LINK_FIELDS: Array<{ key: string; label: string; placeholder: string }> = [
  { key: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/username" },
  { key: "github", label: "GitHub", placeholder: "https://github.com/username" },
  { key: "portfolio", label: "Portfolio", placeholder: "https://yourportfolio.com" },
  { key: "twitter", label: "X / Twitter", placeholder: "https://x.com/username" },
  { key: "instagram", label: "Instagram", placeholder: "https://instagram.com/username" },
  { key: "facebook", label: "Facebook", placeholder: "https://facebook.com/username" },
  { key: "medium", label: "Medium", placeholder: "https://medium.com/@username" },
  { key: "dribbble", label: "Dribbble", placeholder: "https://dribbble.com/username" },
  { key: "behance", label: "Behance", placeholder: "https://behance.net/username" },
  { key: "codepen", label: "CodePen", placeholder: "https://codepen.io/username" },
  { key: "reddit", label: "Reddit", placeholder: "https://reddit.com/u/username" },
  { key: "custom", label: "Custom Link", placeholder: "https://..." },
];

const ALL_ROLES: AccountType[] = ["candidate", "employer", "faculty", "institution"];
const A_PERSON: AccountType[] = ["candidate", "employer", "faculty"];

const SECTION_ITEMS: SectionMeta[] = [
  { key: "basic", label: "Basic Details", description: "Identity and account setup", icon: UserRound, requiredCandidate: true, requiredEmployer: true, roles: ALL_ROLES },
  // A recruiter does not have a CV to upload here, and an institution is not a
  // person. Students and academicians both do.
  { key: "resume", label: "Resume", description: "Upload and manage CV", icon: FileText, requiredCandidate: true, roles: ["candidate", "faculty"] },
  { key: "about", label: "About", description: "Short professional summary", icon: NotebookPen, requiredCandidate: true, roles: ALL_ROLES },
  { key: "skills", label: "Skills", description: "Skills and interests", icon: Sparkles, requiredCandidate: true, roles: ["candidate", "faculty"] },
  { key: "education", label: "Education", description: "Academic information", icon: GraduationCap, requiredCandidate: true, roles: ["candidate", "faculty"] },
  { key: "work", label: "Work Experience", description: "Role and experience", icon: BriefcaseBusiness, roles: A_PERSON },
  { key: "accomplishments", label: "Accomplishments & Initiatives", description: "Projects and achievements", icon: Award, roles: ["candidate", "faculty"] },
  // An organisation has no hobbies and no home address.
  { key: "personal", label: "Personal Details", description: "Address and personal info", icon: MapPinned, roles: A_PERSON },
  { key: "social", label: "Social Links", description: "External profile links", icon: Link2, roles: ALL_ROLES },
];

function toText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function uppercaseProfileText(value: string): string {
  return value.toLocaleUpperCase("en-IN");
}

function normalizeProfileValue<K extends keyof ProfilePayload>(field: K, value: ProfilePayload[K]): ProfilePayload[K] {
  if (typeof value === "string" && UPPERCASE_TEXT_FIELDS.has(field)) {
    return uppercaseProfileText(value) as ProfilePayload[K];
  }
  return value;
}

function findKnownUniversityOption(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return UNIVERSITY_OPTION_BY_UPPERCASE.get(trimmed.toLocaleUpperCase("en-IN")) ?? null;
}

function toNullableNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const output: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const text = String(item || "").trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(text);
  }
  return output;
}

function toStringMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") {
    return {};
  }
  const input = value as Record<string, unknown>;
  const output: Record<string, string> = {};
  Object.entries(input).forEach(([key, raw]) => {
    const cleanKey = String(key || "").trim().toLowerCase();
    const cleanValue = String(raw || "").trim();
    if (!cleanKey || !cleanValue) {
      return;
    }
    output[cleanKey] = cleanValue;
  });
  return output;
}

function hydrateProfilePayload(profilePayload: Record<string, unknown>): ProfilePayload {
  return {
    account_type: (toText(profilePayload.account_type) || "candidate") as AccountType,
    first_name: toText(profilePayload.first_name),
    last_name: toText(profilePayload.last_name),
    mobile: toText(profilePayload.mobile),
    country_code: toText(profilePayload.country_code) || "+91",
    user_type: (toText(profilePayload.user_type) || "") as UserType | "",
    domain: toText(profilePayload.domain),
    course: toText(profilePayload.course),
    course_specialization: toText(profilePayload.course_specialization),
    passout_year: toNullableNumber(profilePayload.passout_year),
    class_grade: toNullableNumber(profilePayload.class_grade),
    current_job_role: toText(profilePayload.current_job_role),
    total_work_experience: toText(profilePayload.total_work_experience),
    experience_summary: toText(profilePayload.experience_summary),
    college_name: toText(profilePayload.college_name),
    company_name: toText(profilePayload.company_name),
    company_website: toText(profilePayload.company_website),
    company_size: toText(profilePayload.company_size),
    company_description: toText(profilePayload.company_description),
    hiring_for: (toText(profilePayload.hiring_for) || "") as "myself" | "others" | "",
    goals: toStringArray(profilePayload.goals),
    career_intent: toStringArray(profilePayload.career_intent),
    preferred_roles: toText(profilePayload.preferred_roles),
    preferred_locations: toText(profilePayload.preferred_locations),
    work_preferences: toStringArray(profilePayload.work_preferences),
    expected_stipend_range: toText(profilePayload.expected_stipend_range),
    availability: toText(profilePayload.availability),
    pan_india: Boolean(profilePayload.pan_india),
    prefer_wfh: Boolean(profilePayload.prefer_wfh),
    consent_data_processing: Boolean(profilePayload.consent_data_processing),
    consent_updates: Boolean(profilePayload.consent_updates),
    bio: toText(profilePayload.bio),
    skills: toText(profilePayload.skills),
    interests: toText(profilePayload.interests),
    interest_graph: toStringArray(profilePayload.interest_graph),
    achievements: toText(profilePayload.achievements),
    education: toText(profilePayload.education),
    education_entries: hydrateEducationEntries(profilePayload.education_entries),
    experience_entries: hydrateExperienceEntries(profilePayload.experience_entries),
    project_entries: hydrateProjectEntries(profilePayload.project_entries),
    certification_entries: hydrateCertificationEntries(profilePayload.certification_entries),
    honor_entries: hydrateHonorEntries(profilePayload.honor_entries),
    volunteer_entries: hydrateVolunteerEntries(profilePayload.volunteer_entries),
    certificates: toText(profilePayload.certificates),
    projects: toText(profilePayload.projects),
    responsibilities: toText(profilePayload.responsibilities),
    current_address_region: toText(profilePayload.current_address_region),
    permanent_address_region: toText(profilePayload.permanent_address_region),
    hobbies: toStringArray(profilePayload.hobbies),
    social_links: toStringMap(profilePayload.social_links),
    resume_url: toText(profilePayload.resume_url),
    resume_filename: toText(profilePayload.resume_filename),
    resume_content_type: toText(profilePayload.resume_content_type),
    resume_uploaded_at: toText(profilePayload.resume_uploaded_at),
  };
}

function assignOptionalText<K extends keyof ProfileUpdatePayload>(target: ProfileUpdatePayload, key: K, value: string): void {
  const trimmed = value.trim();
  if (trimmed.length > 0) {
    (target as Record<string, unknown>)[String(key)] = trimmed;
  }
}

function buildProfileUpdatePayload(profile: ProfilePayload): ProfileUpdatePayload {
  const payload: ProfileUpdatePayload = {
    account_type: profile.account_type,
    pan_india: profile.pan_india,
    prefer_wfh: profile.prefer_wfh,
    consent_data_processing: profile.consent_data_processing,
    consent_updates: profile.consent_updates,
    goals: [...profile.goals],
    career_intent: [...profile.career_intent],
    work_preferences: [...profile.work_preferences],
    hobbies: [...profile.hobbies],
    social_links: Object.fromEntries(
      Object.entries(profile.social_links)
        .map(([key, value]) => [key.trim().toLowerCase(), value.trim()])
        .filter(([key, value]) => key.length > 0 && value.length > 0)
    ),
  };

  // Always sent, so clearing the last entry actually deletes it server-side.
  // Entries with no school are dropped: an empty card the user never filled in
  // should not become a blank row on their profile.
  payload.experience_entries = profile.experience_entries
    .filter((entry) => entry.title.trim().length > 0 || entry.organization.trim().length > 0)
    .map((entry) => ({ ...entry, skills: entry.skills.map((v) => v.trim()).filter(Boolean) }));
  payload.project_entries = profile.project_entries
    .filter((entry) => entry.name.trim().length > 0)
    .map((entry) => ({ ...entry, skills: entry.skills.map((s) => s.trim()).filter(Boolean) }));
  payload.certification_entries = profile.certification_entries
    .filter((entry) => entry.name.trim().length > 0)
    .map((entry) => ({ ...entry, skills: entry.skills.map((s) => s.trim()).filter(Boolean) }));
  payload.honor_entries = profile.honor_entries.filter((entry) => entry.title.trim().length > 0);
  payload.volunteer_entries = profile.volunteer_entries.filter(
    (entry) => entry.organization.trim().length > 0 || entry.role.trim().length > 0
  );

  payload.education_entries = profile.education_entries
    .filter((entry) => entry.school.trim().length > 0)
    .map((entry) => ({
      ...entry,
      school: entry.school.trim(),
      skills: entry.skills.map((skill) => skill.trim()).filter(Boolean),
    }));

  if (profile.user_type) {
    payload.user_type = profile.user_type;
  }
  if (profile.hiring_for) {
    payload.hiring_for = profile.hiring_for;
  }
  if (profile.passout_year !== null) {
    payload.passout_year = profile.passout_year;
  }
  if (profile.class_grade !== null) {
    payload.class_grade = profile.class_grade;
  }

  assignOptionalText(payload, "first_name", profile.first_name);
  assignOptionalText(payload, "last_name", profile.last_name);
  assignOptionalText(payload, "mobile", profile.mobile);
  assignOptionalText(payload, "country_code", profile.country_code);
  assignOptionalText(payload, "domain", profile.domain);
  assignOptionalText(payload, "course", profile.course);
  assignOptionalText(payload, "course_specialization", profile.course_specialization);
  assignOptionalText(payload, "current_job_role", profile.current_job_role);
  assignOptionalText(payload, "total_work_experience", profile.total_work_experience);
  assignOptionalText(payload, "experience_summary", profile.experience_summary);
  assignOptionalText(payload, "college_name", profile.college_name);
  assignOptionalText(payload, "company_name", profile.company_name);
  assignOptionalText(payload, "company_website", profile.company_website);
  assignOptionalText(payload, "company_size", profile.company_size);
  assignOptionalText(payload, "company_description", profile.company_description);
  assignOptionalText(payload, "preferred_roles", profile.preferred_roles);
  assignOptionalText(payload, "preferred_locations", profile.preferred_locations);
  assignOptionalText(payload, "expected_stipend_range", profile.expected_stipend_range);
  assignOptionalText(payload, "availability", profile.availability);
  assignOptionalText(payload, "bio", profile.bio);
  assignOptionalText(payload, "skills", profile.skills);
  assignOptionalText(payload, "interests", profile.interests);
  payload.interest_graph = [...profile.interest_graph];
  assignOptionalText(payload, "achievements", profile.achievements);
  assignOptionalText(payload, "education", profile.education);
  assignOptionalText(payload, "certificates", profile.certificates);
  assignOptionalText(payload, "projects", profile.projects);
  assignOptionalText(payload, "responsibilities", profile.responsibilities);
  assignOptionalText(payload, "current_address_region", profile.current_address_region);
  assignOptionalText(payload, "permanent_address_region", profile.permanent_address_region);

  return payload;
}

function hasText(value: string): boolean {
  return value.trim().length > 0;
}

function splitCommaValues(value: string): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  value
    .split(",")
    .map((item) => item.trim())
    .forEach((item) => {
      const key = item.toLowerCase();
      if (!item || seen.has(key)) {
        return;
      }
      seen.add(key);
      output.push(item);
    });
  return output;
}

function deriveUniversitySelection(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  return findKnownUniversityOption(trimmed) ?? OTHER_UNIVERSITY_VALUE;
}

function getCollegeNameFromProfile(profile: ProfilePayload): string {
  return profile.college_name;
}

// Only the region survives data minimization: it is a ranking input, whereas the
// street line, landmark and pincode were collected and never read by anything.
function getCurrentAddressFromProfile(profile: ProfilePayload): { region: string } {
  return { region: profile.current_address_region };
}

function getPermanentAddressFromProfile(profile: ProfilePayload): { region: string } {
  return { region: profile.permanent_address_region };
}

function getResumeFilenameFromProfile(profile: ProfilePayload): string {
  return profile.resume_filename;
}

const CURRENT_TO_PERMANENT_ADDRESS_FIELD: Partial<Record<keyof ProfilePayload, keyof ProfilePayload>> = {
  current_address_region: "permanent_address_region",
};

export default function ProfilePage() {
  const [activeSection, setActiveSection] = useState<SectionKey>("basic");
  const [copyCurrentAddress, setCopyCurrentAddress] = useState(false);
  const [hobbyInput, setHobbyInput] = useState("");
  // Accomplishments holds four independent lists. Rendering them all expanded
  // made the page grow without bound as entries were added - four lists of
  // cards on one screen - so only one opens at a time.
  const [openAccomplishmentGroup, setOpenAccomplishmentGroup] =
    useState<"projects" | "certifications" | "honors" | "volunteering" | null>("projects");
  const [selectedUniversity, setSelectedUniversity] = useState<string>("");

  const [profile, setProfile] = useState<ProfilePayload>({
    account_type: "candidate",
    first_name: "",
    last_name: "",
    mobile: "",
    country_code: "+91",
    user_type: "",
    domain: "",
    course: "",
    course_specialization: "",
    passout_year: null,
    class_grade: null,
    current_job_role: "",
    total_work_experience: "",
    experience_summary: "",
    college_name: "",
    company_name: "",
    company_website: "",
    company_size: "",
    company_description: "",
    hiring_for: "",
    goals: [],
    career_intent: [],
    preferred_roles: "",
    preferred_locations: "",
    work_preferences: [],
    expected_stipend_range: "",
    availability: "",
    pan_india: false,
    prefer_wfh: false,
    consent_data_processing: false,
    consent_updates: false,
    bio: "",
    skills: "",
    interests: "",
    interest_graph: [],
    achievements: "",
    education: "",
    education_entries: [],
    experience_entries: [],
    project_entries: [],
    certification_entries: [],
    honor_entries: [],
    volunteer_entries: [],
    certificates: "",
    projects: "",
    responsibilities: "",
    current_address_region: "",
    permanent_address_region: "",
    hobbies: [],
    social_links: {},
    resume_url: "",
    resume_filename: "",
    resume_content_type: "",
    resume_uploaded_at: "",
  });
  const {
    loading,
    saving,
    uploadingResume,
    email,
    message,
    error,
    saveProfile,
    uploadResume,
    deleteResume,
    downloadResume,
  } = useProfileData<ProfilePayload, ProfileUpdatePayload>({
    profile,
    setProfile,
    hydrateProfilePayload,
    buildProfileUpdatePayload,
    deriveUniversitySelection,
    hasText,
    getCollegeName: getCollegeNameFromProfile,
    getCurrentAddress: getCurrentAddressFromProfile,
    getPermanentAddress: getPermanentAddressFromProfile,
    getResumeFilename: getResumeFilenameFromProfile,
    setSelectedUniversity,
    setCopyCurrentAddress,
  });

  const updateProfile = <K extends keyof ProfilePayload>(field: K, value: ProfilePayload[K]) => {
    const normalizedValue = normalizeProfileValue(field, value);
    setProfile((prev) => {
      const nextProfile = { ...prev, [field]: normalizedValue };
      if (!copyCurrentAddress) {
        return nextProfile;
      }

      const mirroredField = CURRENT_TO_PERMANENT_ADDRESS_FIELD[field];
      if (!mirroredField) {
        return nextProfile;
      }

      return {
        ...nextProfile,
        [mirroredField]: normalizeProfileValue(mirroredField, normalizedValue as ProfilePayload[typeof mirroredField]),
      };
    });
  };

  const handleCopyCurrentAddressChange = (checked: boolean) => {
    setCopyCurrentAddress(checked);
    if (!checked) {
      return;
    }
    setProfile((prev) => ({
      ...prev,
      permanent_address_region: prev.current_address_region,
    }));
  };

  const toggleGoal = (goal: string) => {
    updateProfile(
      "goals",
      profile.goals.includes(goal) ? profile.goals.filter((item) => item !== goal) : [...profile.goals, goal]
    );
  };

  const addHobby = () => {
    const cleaned = hobbyInput.trim();
    if (!cleaned) {
      return;
    }
    const normalized = uppercaseProfileText(cleaned);
    const exists = profile.hobbies.some((item) => item.toLowerCase() === normalized.toLowerCase());
    if (!exists) {
      updateProfile("hobbies", [...profile.hobbies, normalized]);
    }
    setHobbyInput("");
  };

  const removeHobby = (hobby: string) => {
    updateProfile(
      "hobbies",
      profile.hobbies.filter((item) => item.toLowerCase() !== hobby.toLowerCase())
    );
  };

  const updateSocialLink = (key: string, value: string) => {
    setProfile((prev) => ({
      ...prev,
      social_links: {
        ...prev.social_links,
        [key]: value,
      },
    }));
  };

  const resumeUploadedOn = useMemo(() => {
    if (!profile.resume_uploaded_at) {
      return "";
    }
    const parsed = new Date(profile.resume_uploaded_at);
    if (Number.isNaN(parsed.getTime())) {
      return "";
    }
    return parsed.toLocaleString();
  }, [profile.resume_uploaded_at]);

  const sectionCompletion = useMemo<Record<SectionKey, boolean>>(() => {
    const isCandidate = profile.account_type === "candidate";
    const hasSocial = Object.values(profile.social_links).some((value) => hasText(value));
    return {
      basic: isCandidate
        ? hasText(profile.first_name) && hasText(profile.mobile) && hasText(profile.user_type) && profile.consent_data_processing
        : hasText(profile.first_name) && hasText(profile.mobile) && hasText(profile.company_name) && profile.consent_data_processing,
      resume: isCandidate ? hasText(profile.resume_url) || hasText(profile.resume_filename) : true,
      about: isCandidate ? hasText(profile.bio) : hasText(profile.company_description),
      skills: isCandidate ? hasText(profile.skills) : hasText(profile.current_job_role),
      education: isCandidate ? hasText(profile.college_name) || hasText(profile.education) : true,
      work: hasText(profile.current_job_role) || hasText(profile.total_work_experience) || hasText(profile.experience_summary),
      accomplishments:
        hasText(profile.achievements) || hasText(profile.certificates) || hasText(profile.projects) || hasText(profile.responsibilities),
      personal: hasText(profile.current_address_region) || profile.hobbies.length > 0,
      social: hasSocial,
    };
  }, [profile]);

  const sectionList = useMemo(
    () =>
      SECTION_ITEMS.filter((section) =>
        section.roles.includes((profile.account_type || "candidate") as AccountType),
      ).map((section) => ({
        ...section,
        required: profile.account_type === "candidate" ? Boolean(section.requiredCandidate) : Boolean(section.requiredEmployer),
      })),
    [profile.account_type]
  );

  const completionPercent = useMemo(() => {
    const completed = sectionList.filter((item) => sectionCompletion[item.key]).length;
    return Math.round((completed / sectionList.length) * 100);
  }, [sectionCompletion, sectionList]);

  const isCandidate = profile.account_type === "candidate";
  const isStudentUniversityFlow = isCandidate && (profile.user_type === "college_student" || profile.user_type === "fresher");

  const renderSectionHeader = (title: string, subtitle: string) => (
    <div className="profile-section-head">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      <span className={`profile-state-chip ${sectionCompletion[activeSection] ? "done" : "pending"}`}>
        {sectionCompletion[activeSection] ? <CheckCircle2 size={14} /> : <Circle size={14} />} {sectionCompletion[activeSection] ? "Completed" : "Pending"}
      </span>
    </div>
  );

  const renderUniversityField = (label: string, placeholder: string) => (
    <>
      <SelectField
        wrapperClassName="profile-field"
        label={label}
        value={selectedUniversity}
        onChange={(event) => {
          const selected = event.target.value;
          setSelectedUniversity(selected);
          if (selected === OTHER_UNIVERSITY_VALUE) {
            if (findKnownUniversityOption(profile.college_name)) {
              updateProfile("college_name", "");
            }
            return;
          }
          updateProfile("college_name", selected);
        }}
      >
          <option value="">Select your university</option>
          {UNIVERSITY_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
          <option value={OTHER_UNIVERSITY_VALUE}>{OTHER_INSTITUTION_LABEL}</option>
      </SelectField>
      {selectedUniversity === OTHER_UNIVERSITY_VALUE ? (
        <TextField
          wrapperClassName="profile-field"
          label="Enter University Name"
          value={profile.college_name}
          onChange={(event) => updateProfile("college_name", event.target.value)}
          placeholder={placeholder}
        />
      ) : null}
    </>
  );

  /* Onboarding has always picked the degree from EDUCATION_PROGRAM_OPTIONS while
     Edit Profile left it as free text, so a student who chose "B.Tech (Bachelor
     of Technology)" during signup came back to an unconstrained box and could
     save a variant spelling over it. Same field, same taxonomy, both places.
     Anything already stored that is not in the taxonomy selects Others and stays
     editable, so no existing value is silently dropped. */
  // A <select> only shows a value that matches an <option value> exactly, so a
  // stored "B.TECH (BACHELOR OF TECHNOLOGY)" has to be resolved back to the
  // canonical "B.Tech (Bachelor of Technology)" or the control renders blank.
  const canonicalCourse = !profile.course
    ? ""
    : (EDUCATION_PROGRAM_OPTIONS.find(
        (option) => option.label.toLowerCase() === profile.course.trim().toLowerCase(),
      )?.label ?? "");
  const courseSelectValue = !profile.course ? "" : canonicalCourse || OTHER_COURSE_VALUE;

  const specializationOptions = getFieldOfStudyOptions(canonicalCourse || profile.course, profile.domain);
  const canonicalSpecialization =
    specializationOptions.find(
      (option) => option.toLowerCase() === profile.course_specialization.trim().toLowerCase(),
    ) ?? "";
  const specializationSelectValue = !profile.course_specialization
    ? ""
    : canonicalSpecialization || OTHER_SPECIALIZATION_VALUE;

  const renderCourseField = () => (
    <>
      <SelectField
        wrapperClassName="profile-field"
        label="Course"
        value={courseSelectValue}
        onChange={(event) => {
          const selected = event.target.value;
          if (selected === OTHER_COURSE_VALUE) {
            // Clear only a taxonomy value, so a manual entry survives reselecting Other.
            if (canonicalCourse) {
              updateProfile("course", "");
            }
            return;
          }
          updateProfile("course", selected);
          // The specialization list is derived from the course, so a stale value
          // from the previous course must not survive the switch.
          const nextOptions = getFieldOfStudyOptions(selected, profile.domain);
          if (profile.course_specialization && !nextOptions.includes(profile.course_specialization)) {
            updateProfile("course_specialization", "");
          }
        }}
      >
        <option value="">Select your course</option>
        {EDUCATION_PROGRAM_GROUPS.map((group) => (
          <optgroup key={group} label={group}>
            {EDUCATION_PROGRAM_OPTIONS.filter((option) => option.group === group).map((option) => (
              <option key={option.value} value={option.label}>
                {option.label}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={OTHER_COURSE_VALUE}>Other course (enter manually)</option>
      </SelectField>
      {courseSelectValue === OTHER_COURSE_VALUE ? (
        <TextField
          wrapperClassName="profile-field"
          label="Enter Course"
          value={profile.course}
          onChange={(event) => updateProfile("course", event.target.value)}
          placeholder="Degree or course"
        />
      ) : null}
    </>
  );

  const canonicalCurrentRole = findKnownRole(profile.current_job_role);
  const currentRoleSelectValue = !profile.current_job_role
    ? ""
    : canonicalCurrentRole || OTHER_ROLE_VALUE;

  const renderCurrentRoleField = (placeholder: string) => (
    <>
      <SelectField
        wrapperClassName="profile-field"
        label="Current Role"
        value={currentRoleSelectValue}
        onChange={(event) => {
          const selected = event.target.value;
          if (selected === OTHER_ROLE_VALUE) {
            if (canonicalCurrentRole) {
              updateProfile("current_job_role", "");
            }
            return;
          }
          updateProfile("current_job_role", selected);
        }}
      >
        <option value="">Select your current role</option>
        {ROLE_GROUPS.map((group) => (
          <optgroup key={group} label={group}>
            {ROLE_OPTIONS.filter((option) => option.group === group).map((option) => (
              <option key={option.label} value={option.label}>
                {option.label}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={OTHER_ROLE_VALUE}>Other role (enter manually)</option>
      </SelectField>
      {currentRoleSelectValue === OTHER_ROLE_VALUE ? (
        <TextField
          wrapperClassName="profile-field"
          label="Enter Current Role"
          value={profile.current_job_role}
          onChange={(event) => updateProfile("current_job_role", event.target.value)}
          placeholder={placeholder}
        />
      ) : null}
    </>
  );

  /* Preferred roles and preferred locations are both comma-separated lists, so
     they share one add-and-remove control over two different vocabularies. */
  const renderPreferredRolesField = () => (
    <TaxonomyMultiSelect
      wrapperClassName="profile-field"
      label="Preferred Roles"
      helper="Pick the roles you want to be matched with. Add as many as apply."
      value={profile.preferred_roles}
      onChange={(next) => updateProfile("preferred_roles", next)}
      options={ROLE_OPTIONS}
      groups={ROLE_GROUPS}
      split={splitRoles}
      join={joinRoles}
      addLabel="+ Add a preferred role"
      icon={Workflow}
    />
  );

  const renderPreferredLocationsField = () => (
    <TaxonomyMultiSelect
      wrapperClassName="profile-field"
      label="Preferred Work Locations"
      helper="Add cities, states or a work mode like Remote. Bangalore and Bengaluru count as one."
      value={profile.preferred_locations}
      onChange={(next) => updateProfile("preferred_locations", next)}
      options={LOCATION_OPTIONS}
      groups={LOCATION_GROUPS}
      split={splitLocations}
      join={joinLocations}
      addLabel="+ Add a preferred location"
      icon={MapPinned}
    />
  );

  const renderSpecializationField = () => (
    <>
      <SelectField
        wrapperClassName="profile-field"
        label="Course Specialization"
        value={specializationSelectValue}
        onChange={(event) => {
          const selected = event.target.value;
          if (selected === OTHER_SPECIALIZATION_VALUE) {
            if (canonicalSpecialization) {
              updateProfile("course_specialization", "");
            }
            return;
          }
          updateProfile("course_specialization", selected);
        }}
      >
        <option value="">
          {specializationOptions.length > 0 ? "Select your specialization" : "Select a course first"}
        </option>
        {specializationOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
        <option value={OTHER_SPECIALIZATION_VALUE}>Other specialization (enter manually)</option>
      </SelectField>
      {specializationSelectValue === OTHER_SPECIALIZATION_VALUE ? (
        <TextField
          wrapperClassName="profile-field"
          label="Enter Specialization"
          value={profile.course_specialization}
          onChange={(event) => updateProfile("course_specialization", event.target.value)}
          placeholder="Your specialization"
        />
      ) : null}
    </>
  );

  const renderBasicSection = () => (
    <>
      {renderSectionHeader("Basic Details", "Identity, user type, and role preferences")}

      <div className="profile-field-grid two">
        <TextField
          wrapperClassName="profile-field"
          label="First Name *"
          value={profile.first_name}
          onChange={(event) => updateProfile("first_name", event.target.value)}
          placeholder="First name"
        />
        <TextField
          wrapperClassName="profile-field"
          label="Last Name"
          value={profile.last_name}
          onChange={(event) => updateProfile("last_name", event.target.value)}
          placeholder="Last name"
        />
      </div>

      <div className="profile-field-grid two">
        <TextField wrapperClassName="profile-field" label="Email" value={email} disabled />
        <TextField
          wrapperClassName="profile-field"
          label="Account Type"
          value={accountRole(profile.account_type)?.label ?? "Student"}
          disabled
        />
      </div>

      <div className="profile-field-grid two">
        <TextField
          wrapperClassName="profile-field"
          label="Country Code"
          value={profile.country_code}
          onChange={(event) => updateProfile("country_code", event.target.value)}
          placeholder="+91"
        />
        <TextField
          wrapperClassName="profile-field"
          label="Mobile *"
          value={profile.mobile}
          onChange={(event) => updateProfile("mobile", event.target.value)}
          placeholder="Enter mobile number"
        />
      </div>

      {isCandidate ? (
        <>
          <FormSection className="profile-field" label="User Type *">
            <PillGroup className="profile-pill-row">
              {USER_TYPE_OPTIONS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`profile-pill ${profile.user_type === item.key ? "active" : ""}`}
                  onClick={() => updateProfile("user_type", item.key)}
                >
                  {item.label}
                </button>
              ))}
            </PillGroup>
          </FormSection>

          <FormSection className="profile-field" label="Domain">
            <PillGroup className="profile-pill-row">
              {DOMAIN_OPTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  // Compared case-insensitively so values stored uppercase by the
                  // old normaliser still light their pill instead of reading as
                  // nothing-selected.
                  className={`profile-pill ${
                    profile.domain.trim().toLowerCase() === item.toLowerCase() ? "active" : ""
                  }`}
                  onClick={() => updateProfile("domain", item)}
                >
                  {item}
                </button>
              ))}
            </PillGroup>
          </FormSection>

          <div className="profile-field-grid two">
            {renderCourseField()}
            {renderSpecializationField()}
          </div>

          <div className="profile-field-grid two">
            <TextField
              wrapperClassName="profile-field"
              label="Passout Year"
              type="number"
              value={profile.passout_year ?? ""}
              onChange={(event) => updateProfile("passout_year", event.target.value ? Number(event.target.value) : null)}
              placeholder="2027"
            />
            <TextField
              wrapperClassName="profile-field"
              label="Class / Grade"
              type="number"
              value={profile.class_grade ?? ""}
              onChange={(event) => updateProfile("class_grade", event.target.value ? Number(event.target.value) : null)}
              placeholder="12"
            />
          </div>

          <div className="profile-field-grid two">
            {renderCurrentRoleField("Student / Analyst / Developer")}
            <TextField
              wrapperClassName="profile-field"
              label="Total Work Experience"
              value={profile.total_work_experience}
              onChange={(event) => updateProfile("total_work_experience", event.target.value)}
              placeholder="0-1 years"
            />
          </div>

          {isStudentUniversityFlow
            ? renderUniversityField("College / University", "Type your university name manually")
            : (
                <TextField
                  wrapperClassName="profile-field"
                  label="College / University"
                  value={profile.college_name}
                  onChange={(event) => updateProfile("college_name", event.target.value)}
                  placeholder="Your institute name"
                />
              )}

          <FormSection className="profile-field" label="Purpose / Goals">
            <PillGroup className="profile-pill-row">
              {GOAL_OPTIONS.map((goal) => (
                <button
                  key={goal}
                  type="button"
                  className={`profile-pill ${profile.goals.includes(goal) ? "active" : ""}`}
                  onClick={() => toggleGoal(goal)}
                >
                  {goal}
                </button>
              ))}
            </PillGroup>
          </FormSection>

          <div className="profile-field-grid two">
            {renderPreferredRolesField()}
            {renderPreferredLocationsField()}
          </div>

          <div className="profile-field-grid two">
            <TextField
              wrapperClassName="profile-field"
              label="Expected Stipend"
              value={profile.expected_stipend_range}
              onChange={(event) => updateProfile("expected_stipend_range", event.target.value)}
              placeholder="₹20,000–₹35,000 per month"
            />
            <SelectField
              wrapperClassName="profile-field"
              label="Availability"
              value={profile.availability}
              onChange={(event) => updateProfile("availability", event.target.value)}
            >
              <option value="">Select availability</option>
              <option value="immediately">Available immediately</option>
              <option value="within_1_month">Available within 1 month</option>
              <option value="within_3_months">Available within 3 months</option>
              <option value="exploring">Exploring opportunities</option>
            </SelectField>
          </div>

          <div className="profile-inline-group">
            <ToggleRow className="profile-inline-check" checked={profile.pan_india} onChange={(checked) => updateProfile("pan_india", checked)}>
              Open to opportunities across India
            </ToggleRow>
            <ToggleRow className="profile-inline-check" checked={profile.prefer_wfh} onChange={(checked) => updateProfile("prefer_wfh", checked)}>
              Prefer work from home
            </ToggleRow>
          </div>
        </>
      ) : (
        <>
          <div className="profile-field-grid two">
            <TextField
              wrapperClassName="profile-field"
              label="Company Name *"
              value={profile.company_name}
              onChange={(event) => updateProfile("company_name", event.target.value)}
              placeholder="Your organization"
            />
            {renderCurrentRoleField("Founder / Recruiter / HR")}
          </div>

          <div className="profile-field-grid two">
            <TextField
              wrapperClassName="profile-field"
              label="Company Website"
              value={profile.company_website}
              onChange={(event) => updateProfile("company_website", event.target.value)}
              placeholder="https://company.com"
            />
            <TextField
              wrapperClassName="profile-field"
              label="Company Size"
              value={profile.company_size}
              onChange={(event) => updateProfile("company_size", event.target.value)}
              placeholder="11-50"
            />
          </div>

          <FormSection className="profile-field" label="Hiring For *">
            <PillGroup className="profile-pill-row">
              {[
                { key: "myself", label: "Myself" },
                { key: "others", label: "Others" },
              ].map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`profile-pill ${profile.hiring_for === item.key ? "active" : ""}`}
                  onClick={() => updateProfile("hiring_for", item.key as "myself" | "others")}
                >
                  {item.label}
                </button>
              ))}
            </PillGroup>
          </FormSection>
        </>
      )}

      <div className="profile-inline-group">
        <ToggleRow
          className="profile-inline-check"
          checked={profile.consent_data_processing}
          onChange={(checked) => updateProfile("consent_data_processing", checked)}
        >
          Include my activity in analytics *
        </ToggleRow>
        {/* The toggle now controls something specific, so it says what. It used to
            read "I agree to data processing and privacy terms" and link to nothing,
            while gating no behaviour at all. */}
        <p className="profile-consent-note">
          Turning this off excludes your activity from our analytics warehouse. Your
          recommendations keep working either way. See the{" "}
          <Link href="/privacy">Privacy Policy</Link> and{" "}
          <Link href="/terms">Terms of Service</Link>.
        </p>
        <ToggleRow className="profile-inline-check" checked={profile.consent_updates} onChange={(checked) => updateProfile("consent_updates", checked)}>
          I want product and opportunity updates
        </ToggleRow>
      </div>

      <DeleteAccountPanel />
    </>
  );

  const renderResumeSection = () => (
    <>
      {renderSectionHeader("Resume", "Upload your latest resume and manage download access")}

      <div className="profile-resume-card">
        {profile.resume_filename ? (
          <>
            <div className="profile-resume-file">
              <FileText size={28} />
              <div>
                <p>{profile.resume_filename}</p>
                <span>{resumeUploadedOn ? `Uploaded ${resumeUploadedOn}` : "Uploaded"}</span>
              </div>
            </div>
            <div className="profile-resume-actions">
              <button type="button" className="btn-secondary" onClick={() => void downloadResume()}>
                <Download size={15} /> View / Download
              </button>
              <button type="button" className="btn-secondary" onClick={() => void deleteResume()} disabled={uploadingResume}>
                <Trash2 size={15} /> Remove
              </button>
            </div>
          </>
        ) : (
          <p className="profile-resume-empty">No resume uploaded yet.</p>
        )}

        <label className={`btn-primary profile-upload-btn ${uploadingResume ? "is-disabled" : ""}`}>
          <Upload size={15} /> {uploadingResume ? "Uploading..." : profile.resume_filename ? "Replace Resume" : "Upload Resume"}
          <input
            type="file"
            accept=".txt,.pdf,.doc,.docx"
            disabled={uploadingResume}
            className="vv-hidden-input"
            onChange={(event) => {
              const nextFile = event.target.files?.[0];
              if (!nextFile) {
                return;
              }
              void uploadResume(nextFile);
              event.currentTarget.value = "";
            }}
          />
        </label>
        <p className="profile-section-footnote">Supported formats: .txt, .pdf, .doc, .docx (max 8 MB).</p>
        {profile.account_type === "candidate" && profile.resume_filename ? (
          <ResumeReadinessReview resumeFilename={profile.resume_filename} />
        ) : null}
      </div>
    </>
  );

  const renderAboutSection = () => (
    <>
      {renderSectionHeader("About", "Introduce yourself in a concise, professional way")}
      <TextareaField
        wrapperClassName="profile-field"
        label={`${isCandidate ? "About Me" : "Company Description"} ${isCandidate ? "*" : ""}`}
        rows={7}
        value={isCandidate ? profile.bio : profile.company_description}
        onChange={(event) => (isCandidate ? updateProfile("bio", event.target.value) : updateProfile("company_description", event.target.value))}
        placeholder={
          isCandidate
            ? "Write a short profile summary (career goals, strengths, and interests)."
            : "Tell candidates what your organization does and what opportunities you offer."
        }
      />
    </>
  );

  const renderSkillsSection = () => (
    <>
      {renderSectionHeader("Skills", "Highlight your skills and areas of interest")}
      <div className="profile-field-grid two">
        <div>
          <SkillAutocompleteInput
            wrapperClassName="profile-field"
            label="Skills *"
            value={profile.skills}
            onChange={(nextValue) => updateProfile("skills", nextValue)}
            placeholder="Python, Data Analysis, C++, SQL, Communication"
          />
        </div>
        <div>
          <TextareaField
            wrapperClassName="profile-field"
            label="Interests"
            rows={5}
            value={profile.interests}
            onChange={(event) => updateProfile("interests", event.target.value)}
            placeholder="Machine Learning, Product, Design, Public Speaking"
          />
          {splitCommaValues(profile.interests).length > 0 ? (
            <div className="profile-tag-row">
              {splitCommaValues(profile.interests).map((interest) => (
                <span key={interest} className="profile-tag">
                  {interest}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </>
  );

  const updateEducationEntry = (index: number, patch: Partial<EducationEntryValue>) => {
    updateProfile(
      "education_entries",
      profile.education_entries.map((entry, position) =>
        position === index ? { ...entry, ...patch } : entry
      )
    );
  };

  const addEducationEntry = () => {
    updateProfile("education_entries", [...profile.education_entries, { ...EMPTY_EDUCATION_ENTRY }]);
  };

  const removeEducationEntry = (index: number) => {
    updateProfile(
      "education_entries",
      profile.education_entries.filter((_, position) => position !== index)
    );
  };

  const renderMonthYearPair = (
    legend: string,
    month: number | null,
    year: number | null,
    onMonth: (value: number | null) => void,
    onYear: (value: number | null) => void
  ) => (
    <div className="profile-field">
      <span className="profile-entry-legend">{legend}</span>
      <div className="profile-field-grid two">
        <SelectField
          wrapperClassName="profile-field"
          label="Month"
          value={month === null ? "" : String(month)}
          onChange={(event) => onMonth(event.target.value ? Number(event.target.value) : null)}
        >
          <option value="">Month</option>
          {MONTH_OPTIONS.map((name, position) => (
            <option key={name} value={position + 1}>{name}</option>
          ))}
        </SelectField>
        <SelectField
          wrapperClassName="profile-field"
          label="Year"
          value={year === null ? "" : String(year)}
          onChange={(event) => onYear(event.target.value ? Number(event.target.value) : null)}
        >
          <option value="">Year</option>
          {YEAR_OPTIONS.map((value) => (
            <option key={value} value={value}>{value}</option>
          ))}
        </SelectField>
      </div>
    </div>
  );

  const renderEducationSection = () => (
    <>
      {renderSectionHeader("Education", "Academic background and qualifications")}

      {profile.education_entries.length === 0 ? (
        <p className="profile-entry-empty">
          No education added yet. Add your school, college, or any other qualification.
        </p>
      ) : null}

      {profile.education_entries.map((entry, index) => (
        <div className="profile-entry-card" key={`education-${index}`}>
          <div className="profile-entry-card-head">
            <span className="profile-entry-card-title">
              {entry.school.trim() || `Education ${index + 1}`}
            </span>
            <button
              type="button"
              className="btn-secondary profile-entry-remove"
              onClick={() => removeEducationEntry(index)}
            >
              Remove
            </button>
          </div>

          <div className="profile-field-grid two">
            <TextField
              wrapperClassName="profile-field"
              label="School"
              required
              value={entry.school}
              onChange={(event) => updateEducationEntry(index, { school: event.target.value })}
              placeholder="Ex: Lovely Professional University"
            />
            <TextField
              wrapperClassName="profile-field"
              label="Degree"
              value={entry.degree}
              onChange={(event) => updateEducationEntry(index, { degree: event.target.value })}
              placeholder="Ex: Bachelor of Technology"
            />
          </div>

          <TextField
            wrapperClassName="profile-field"
            label="Field of study"
            value={entry.field_of_study}
            onChange={(event) => updateEducationEntry(index, { field_of_study: event.target.value })}
            placeholder="Ex: Computer Science"
          />

          <div className="profile-field-grid two">
            {renderMonthYearPair(
              "Start date",
              entry.start_month,
              entry.start_year,
              (value) => updateEducationEntry(index, { start_month: value }),
              (value) => updateEducationEntry(index, { start_year: value })
            )}
            {renderMonthYearPair(
              "End date (or expected)",
              entry.end_month,
              entry.end_year,
              (value) => updateEducationEntry(index, { end_month: value }),
              (value) => updateEducationEntry(index, { end_year: value })
            )}
          </div>

          <TextField
            wrapperClassName="profile-field"
            label="Grade"
            value={entry.grade}
            onChange={(event) => updateEducationEntry(index, { grade: event.target.value })}
            placeholder="Ex: 8.16 CGPA"
          />

          <TextareaField
            wrapperClassName="profile-field"
            label="Activities and societies"
            rows={3}
            value={entry.activities}
            onChange={(event) => updateEducationEntry(index, { activities: event.target.value })}
            placeholder="Ex: Coding club, robotics team, student council"
          />

          <TextareaField
            wrapperClassName="profile-field"
            label="Description"
            rows={4}
            value={entry.description}
            onChange={(event) => updateEducationEntry(index, { description: event.target.value })}
            placeholder="Coursework, thesis, and milestones worth calling out."
          />

          <TextField
            wrapperClassName="profile-field"
            label="Skills"
            helper="Comma separated. These also feed your Skills section."
            value={entry.skills.join(", ")}
            onChange={(event) =>
              updateEducationEntry(index, {
                skills: event.target.value.split(",").map((skill) => skill.trim()).filter(Boolean),
              })
            }
            placeholder="Ex: Python, Data Structures, DBMS"
          />
        </div>
      ))}

      <button type="button" className="btn-secondary profile-entry-add" onClick={addEducationEntry}>
        + Add education
      </button>
    </>
  );

  const renderWorkSection = () => {
    const roles = listUpdater("experience_entries");
    return (
      <>
        {renderSectionHeader("Work Experience", "Roles, internships, and what you did in them")}

        {profile.experience_entries.length === 0 ? (
          <p className="profile-entry-empty">No roles added yet.</p>
        ) : null}

        {profile.experience_entries.map((entry, index) =>
          renderEntryCard(
            entry.title.trim() || entry.organization.trim() || `Role ${index + 1}`,
            index,
            () => roles.remove(index),
            (
              <>
                <div className="profile-field-grid two">
                  <TextField wrapperClassName="profile-field" label="Title" required value={entry.title}
                    onChange={(e) => roles.patch(index, { title: e.target.value })}
                    placeholder="Ex: SDE Intern" />
                  <TextField wrapperClassName="profile-field" label="Company or organization" required
                    value={entry.organization}
                    onChange={(e) => roles.patch(index, { organization: e.target.value })}
                    placeholder="Ex: Stripe" />
                </div>
                <div className="profile-field-grid two">
                  <SelectField wrapperClassName="profile-field" label="Employment type"
                    value={entry.employment_type}
                    onChange={(e) => roles.patch(index, { employment_type: e.target.value })}>
                    <option value="">Select</option>
                    {EMPLOYMENT_TYPES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </SelectField>
                  <SelectField wrapperClassName="profile-field" label="Location type"
                    value={entry.location_type}
                    onChange={(e) => roles.patch(index, { location_type: e.target.value })}>
                    <option value="">Select</option>
                    {LOCATION_TYPES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </SelectField>
                </div>
                <TextField wrapperClassName="profile-field" label="Location" value={entry.location}
                  onChange={(e) => roles.patch(index, { location: e.target.value })}
                  placeholder="Ex: Bengaluru, India" />
                <label className="profile-entry-checkbox">
                  <input type="checkbox" checked={entry.is_current}
                    onChange={(e) => roles.patch(index, { is_current: e.target.checked })} />
                  <span>I am currently working in this role</span>
                </label>
                <div className="profile-field-grid two">
                  {renderMonthYearPair("Start date", entry.start_month, entry.start_year,
                    (v) => roles.patch(index, { start_month: v }),
                    (v) => roles.patch(index, { start_year: v }))}
                  {entry.is_current
                    ? null
                    : renderMonthYearPair("End date", entry.end_month, entry.end_year,
                        (v) => roles.patch(index, { end_month: v }),
                        (v) => roles.patch(index, { end_year: v }))}
                </div>
                <TextareaField wrapperClassName="profile-field" label="Highlights" rows={5}
                  value={entry.highlights}
                  onChange={(e) => roles.patch(index, { highlights: e.target.value })}
                  placeholder="Impact, ownership, tools used, and outcomes." />
                {renderSkillsField(entry.skills, (next) => roles.patch(index, { skills: next }))}
              </>
            )
          )
        )}

        <button type="button" className="btn-secondary profile-entry-add"
          onClick={() => roles.add(EMPTY_EXPERIENCE_ENTRY)}>+ Add role</button>

        {/* Total experience stays a plain field: it is a self-reported summary
            the ranker reads, not something derivable from the roles above while
            a student is still filling them in. */}
        <TextField
          wrapperClassName="profile-field"
          label="Total Work Experience"
          value={profile.total_work_experience}
          onChange={(event) => updateProfile("total_work_experience", event.target.value)}
          placeholder="6 months / 1.5 years"
        />
      </>
    );
  };

  // Generic list helpers: every accomplishment list is add / patch-at-index /
  // remove-at-index, so they share one implementation rather than four copies.
  const listUpdater = <K extends keyof ProfilePayload>(field: K) => ({
    patch: (index: number, patch: Record<string, unknown>) =>
      updateProfile(
        field,
        (profile[field] as unknown as Record<string, unknown>[]).map((entry, position) =>
          position === index ? { ...entry, ...patch } : entry
        ) as ProfilePayload[K]
      ),
    add: (blank: Record<string, unknown>) =>
      updateProfile(field, [
        ...(profile[field] as unknown as Record<string, unknown>[]),
        { ...blank },
      ] as ProfilePayload[K]),
    remove: (index: number) =>
      updateProfile(
        field,
        (profile[field] as unknown as Record<string, unknown>[]).filter(
          (_, position) => position !== index
        ) as ProfilePayload[K]
      ),
  });

  const renderEntryCard = (
    title: string,
    index: number,
    onRemove: () => void,
    children: React.ReactNode
  ) => (
    <div className="profile-entry-card" key={`${title}-${index}`}>
      <div className="profile-entry-card-head">
        <span className="profile-entry-card-title">{title}</span>
        <button type="button" className="btn-secondary profile-entry-remove" onClick={onRemove}>
          Remove
        </button>
      </div>
      {children}
    </div>
  );

  const renderCollapsibleGroup = (
    key: "projects" | "certifications" | "honors" | "volunteering",
    title: string,
    count: number,
    children: React.ReactNode
  ) => {
    const open = openAccomplishmentGroup === key;
    return (
      <div className={`profile-entry-group ${open ? "is-open" : ""}`}>
        <button
          type="button"
          className="profile-entry-group-toggle"
          aria-expanded={open}
          onClick={() => setOpenAccomplishmentGroup(open ? null : key)}
        >
          <span className="profile-entry-group-label">
            {title}
            {/* The count is what makes a collapsed group readable: without it a
                closed section gives no clue whether anything is in there. */}
            <span className="profile-entry-group-count">{count}</span>
          </span>
          <span className="profile-entry-group-chevron" aria-hidden="true">
            {open ? "\u2212" : "+"}
          </span>
        </button>
        {open ? <div className="profile-entry-group-body">{children}</div> : null}
      </div>
    );
  };

  const renderSkillsField = (skills: string[], onChange: (next: string[]) => void) => (
    <TextField
      wrapperClassName="profile-field"
      label="Skills"
      helper="Comma separated. These also feed your Skills section."
      value={skills.join(", ")}
      onChange={(event) =>
        onChange(event.target.value.split(",").map((skill) => skill.trim()).filter(Boolean))
      }
      placeholder="Ex: FastAPI, PostgreSQL"
    />
  );

  const renderAccomplishmentsSection = () => {
    const projects = listUpdater("project_entries");
    const certs = listUpdater("certification_entries");
    const honors = listUpdater("honor_entries");
    const volunteering = listUpdater("volunteer_entries");

    return (
      <>
        {renderSectionHeader(
          "Accomplishments & Initiatives",
          "Projects, certifications, awards, and volunteering"
        )}

        {renderCollapsibleGroup("projects", "Projects", profile.project_entries.length, (
          <>
        {profile.project_entries.length === 0 ? (
          <p className="profile-entry-empty">No projects added yet.</p>
        ) : null}
        {profile.project_entries.map((entry, index) =>
          renderEntryCard(entry.name.trim() || `Project ${index + 1}`, index, () => projects.remove(index), (
            <>
              <TextField
                wrapperClassName="profile-field"
                label="Project name"
                required
                value={entry.name}
                onChange={(event) => projects.patch(index, { name: event.target.value })}
                placeholder="Ex: VidyaVerse"
              />
              <TextareaField
                wrapperClassName="profile-field"
                label="Description"
                rows={4}
                value={entry.description}
                onChange={(event) => projects.patch(index, { description: event.target.value })}
                placeholder="What it does and what it achieved."
              />
              <TextField
                wrapperClassName="profile-field"
                label="Link"
                value={entry.url}
                onChange={(event) => projects.patch(index, { url: event.target.value })}
                placeholder="https://"
              />
              <label className="profile-entry-checkbox">
                <input
                  type="checkbox"
                  checked={entry.is_current}
                  onChange={(event) => projects.patch(index, { is_current: event.target.checked })}
                />
                <span>I am currently working on this project</span>
              </label>
              <div className="profile-field-grid two">
                {renderMonthYearPair("Start date", entry.start_month, entry.start_year,
                  (v) => projects.patch(index, { start_month: v }),
                  (v) => projects.patch(index, { start_year: v }))}
                {entry.is_current
                  ? null
                  : renderMonthYearPair("End date", entry.end_month, entry.end_year,
                      (v) => projects.patch(index, { end_month: v }),
                      (v) => projects.patch(index, { end_year: v }))}
              </div>
              {renderSkillsField(entry.skills, (next) => projects.patch(index, { skills: next }))}
            </>
          ))
        )}
        <button type="button" className="btn-secondary profile-entry-add"
          onClick={() => projects.add(EMPTY_PROJECT_ENTRY)}>+ Add project</button>
          </>
        ))}


        {renderCollapsibleGroup("certifications", "Licenses &amp; certifications", profile.certification_entries.length, (
          <>
        {profile.certification_entries.length === 0 ? (
          <p className="profile-entry-empty">No certifications added yet.</p>
        ) : null}
        {profile.certification_entries.map((entry, index) =>
          renderEntryCard(entry.name.trim() || `Certification ${index + 1}`, index, () => certs.remove(index), (
            <>
              <div className="profile-field-grid two">
                <TextField wrapperClassName="profile-field" label="Name" required value={entry.name}
                  onChange={(e) => certs.patch(index, { name: e.target.value })}
                  placeholder="Ex: Redis Associate Developer" />
                <TextField wrapperClassName="profile-field" label="Issuing organization"
                  value={entry.issuing_organization}
                  onChange={(e) => certs.patch(index, { issuing_organization: e.target.value })}
                  placeholder="Ex: Redis" />
              </div>
              <div className="profile-field-grid two">
                {renderMonthYearPair("Issue date", entry.issue_month, entry.issue_year,
                  (v) => certs.patch(index, { issue_month: v }),
                  (v) => certs.patch(index, { issue_year: v }))}
                {renderMonthYearPair("Expiration date", entry.expiry_month, entry.expiry_year,
                  (v) => certs.patch(index, { expiry_month: v }),
                  (v) => certs.patch(index, { expiry_year: v }))}
              </div>
              <div className="profile-field-grid two">
                <TextField wrapperClassName="profile-field" label="Credential ID" value={entry.credential_id}
                  onChange={(e) => certs.patch(index, { credential_id: e.target.value })} />
                <TextField wrapperClassName="profile-field" label="Credential URL" value={entry.credential_url}
                  onChange={(e) => certs.patch(index, { credential_url: e.target.value })}
                  placeholder="https://" />
              </div>
              {renderSkillsField(entry.skills, (next) => certs.patch(index, { skills: next }))}
            </>
          ))
        )}
        <button type="button" className="btn-secondary profile-entry-add"
          onClick={() => certs.add(EMPTY_CERTIFICATION_ENTRY)}>+ Add certification</button>
          </>
        ))}


        {renderCollapsibleGroup("honors", "Honors &amp; awards", profile.honor_entries.length, (
          <>
        {profile.honor_entries.length === 0 ? (
          <p className="profile-entry-empty">No honors added yet.</p>
        ) : null}
        {profile.honor_entries.map((entry, index) =>
          renderEntryCard(entry.title.trim() || `Honor ${index + 1}`, index, () => honors.remove(index), (
            <>
              <div className="profile-field-grid two">
                <TextField wrapperClassName="profile-field" label="Title" required value={entry.title}
                  onChange={(e) => honors.patch(index, { title: e.target.value })}
                  placeholder="Ex: Rank 2 - Graph Cadence" />
                <TextField wrapperClassName="profile-field" label="Issuer" value={entry.issuer}
                  onChange={(e) => honors.patch(index, { issuer: e.target.value })}
                  placeholder="Ex: AlgoUniversity" />
              </div>
              {renderMonthYearPair("Issue date", entry.issue_month, entry.issue_year,
                (v) => honors.patch(index, { issue_month: v }),
                (v) => honors.patch(index, { issue_year: v }))}
              <TextareaField wrapperClassName="profile-field" label="Description" rows={4}
                value={entry.description}
                onChange={(e) => honors.patch(index, { description: e.target.value })}
                placeholder="What the award was for." />
            </>
          ))
        )}
        <button type="button" className="btn-secondary profile-entry-add"
          onClick={() => honors.add(EMPTY_HONOR_ENTRY)}>+ Add honor</button>
          </>
        ))}


        {renderCollapsibleGroup("volunteering", "Volunteering", profile.volunteer_entries.length, (
          <>
        {profile.volunteer_entries.length === 0 ? (
          <p className="profile-entry-empty">No volunteering added yet.</p>
        ) : null}
        {profile.volunteer_entries.map((entry, index) =>
          renderEntryCard(
            entry.role.trim() || entry.organization.trim() || `Volunteering ${index + 1}`,
            index,
            () => volunteering.remove(index),
            (
              <>
                <div className="profile-field-grid two">
                  <TextField wrapperClassName="profile-field" label="Organization" required
                    value={entry.organization}
                    onChange={(e) => volunteering.patch(index, { organization: e.target.value })}
                    placeholder="Ex: Red Cross" />
                  <TextField wrapperClassName="profile-field" label="Role" required value={entry.role}
                    onChange={(e) => volunteering.patch(index, { role: e.target.value })}
                    placeholder="Ex: Educator" />
                </div>
                <TextField wrapperClassName="profile-field" label="Cause" value={entry.cause}
                  onChange={(e) => volunteering.patch(index, { cause: e.target.value })}
                  placeholder="Ex: Environment" />
                <label className="profile-entry-checkbox">
                  <input type="checkbox" checked={entry.is_current}
                    onChange={(e) => volunteering.patch(index, { is_current: e.target.checked })} />
                  <span>I am currently volunteering in this role</span>
                </label>
                <div className="profile-field-grid two">
                  {renderMonthYearPair("Start date", entry.start_month, entry.start_year,
                    (v) => volunteering.patch(index, { start_month: v }),
                    (v) => volunteering.patch(index, { start_year: v }))}
                  {entry.is_current
                    ? null
                    : renderMonthYearPair("End date", entry.end_month, entry.end_year,
                        (v) => volunteering.patch(index, { end_month: v }),
                        (v) => volunteering.patch(index, { end_year: v }))}
                </div>
                <TextareaField wrapperClassName="profile-field" label="Description" rows={4}
                  value={entry.description}
                  onChange={(e) => volunteering.patch(index, { description: e.target.value })}
                  placeholder="What you did and the impact it had." />
              </>
            )
          )
        )}
        <button type="button" className="btn-secondary profile-entry-add"
          onClick={() => volunteering.add(EMPTY_VOLUNTEER_ENTRY)}>+ Add volunteering</button>
          </>
        ))}

      </>
    );
  };

  const renderPersonalSection = () => (
    <>
      {renderSectionHeader("Personal Details", "Where you are based, and your personal interests")}

      <BackupEmailPanel />

      <div className="profile-address-card">
        <h3>Current Location</h3>
        <p className="profile-address-note">
          City and state only. We use this to match opportunities near you — we do not ask for a
          street address, and we do not need one.
        </p>
        <div className="profile-field-grid two">
          <TextField
            wrapperClassName="profile-field"
            label="City / Region"
            value={profile.current_address_region}
            onChange={(event) => updateProfile("current_address_region", event.target.value)}
            placeholder="City, State, Country"
          />
        </div>
      </div>

      <div className="profile-address-card">
        <div className="profile-address-head">
          <h3>Home Location</h3>
          <ToggleRow className="profile-inline-check" checked={copyCurrentAddress} onChange={handleCopyCurrentAddressChange}>
            Same as current
          </ToggleRow>
        </div>

        <div className="profile-field-grid two">
          <TextField
            wrapperClassName="profile-field"
            label="City / Region"
            value={profile.permanent_address_region}
            onChange={(event) => updateProfile("permanent_address_region", event.target.value)}
            placeholder="City, State, Country"
          />
        </div>
      </div>

      <FormSection className="profile-field" label="Hobbies">
        <div className="profile-hobby-input-row">
          <input
            className="input-base"
            value={hobbyInput}
            onChange={(event) => setHobbyInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addHobby();
              }
            }}
            placeholder="Type hobby and press Enter"
          />
          <button type="button" className="btn-secondary" onClick={addHobby}>
            Add
          </button>
        </div>
        {profile.hobbies.length > 0 ? (
          <div className="profile-tag-row">
            {profile.hobbies.map((hobby) => (
              <span key={hobby} className="profile-tag removable">
                {hobby}
                <button type="button" onClick={() => removeHobby(hobby)} aria-label={`Remove ${hobby}`}>
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </FormSection>
    </>
  );

  const renderSocialSection = () => {
    const knownKeys = new Set(SOCIAL_LINK_FIELDS.map((field) => field.key));
    const extraSocialEntries = Object.entries(profile.social_links).filter(([key]) => !knownKeys.has(key));

    return (
      <>
        {renderSectionHeader("Social Links", "Add public links to your profiles and portfolio")}
        <div className="profile-social-grid">
          {SOCIAL_LINK_FIELDS.map((field) => (
            <TextField
              key={field.key}
              wrapperClassName="profile-field"
              label={field.label}
              value={profile.social_links[field.key] || ""}
              onChange={(event) => updateSocialLink(field.key, event.target.value)}
              placeholder={field.placeholder}
            />
          ))}

          {extraSocialEntries.map(([key, value]) => (
            <TextField
              key={key}
              wrapperClassName="profile-field"
              label={key.replace(/_/g, " ")}
              value={value}
              onChange={(event) => updateSocialLink(key, event.target.value)}
              placeholder="https://..."
            />
          ))}
        </div>
      </>
    );
  };

  const renderActiveSection = () => {
    switch (activeSection) {
      case "basic":
        return renderBasicSection();
      case "resume":
        return renderResumeSection();
      case "about":
        return renderAboutSection();
      case "skills":
        return renderSkillsSection();
      case "education":
        return renderEducationSection();
      case "work":
        return renderWorkSection();
      case "accomplishments":
        return renderAccomplishmentsSection();
      case "personal":
        return renderPersonalSection();
      case "social":
        return renderSocialSection();
      default:
        return renderBasicSection();
    }
  };

  if (loading) {
    return (
      <div className="profile-page-root">
        <Sidebar />
        <main className="main-content">
          <CenteredPageSkeleton paneHeight="700px" />
        </main>
      </div>
    );
  }

  return (
    <div className="profile-page-root">
      <Sidebar />
      <main className="main-content">
        <section className="card-panel profile-editor-shell">
          <header className="profile-editor-header">
            <div className="profile-title-wrap">
              <span className="profile-title-icon">
                <Workflow size={20} />
              </span>
              <div>
                <h1>Edit Profile</h1>
                <p>Professional profile builder aligned with your app theme.</p>
              </div>
            </div>
            <div className="profile-header-actions">
              <Link href={landingPathForAccountType(profile.account_type)} className="btn-secondary">
                Back
              </Link>
              <button type="button" className="btn-primary" onClick={() => void saveProfile()} disabled={saving}>
                <Save size={15} /> {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </header>

          {error ? <div className="profile-alert error">{error}</div> : null}
          {message ? <div className="profile-alert success">{message}</div> : null}

          <div className="profile-workspace">
            <aside className="profile-nav-pane">
              <div className="profile-progress-card">
                <div className="profile-progress-head">
                  <span>Profile completion</span>
                  <strong>{completionPercent}%</strong>
                </div>
                <div className="profile-progress-track" aria-hidden>
                  <span style={{ width: `${completionPercent}%` }} />
                </div>
                <p>
                  Complete required sections to improve profile strength and recommendation quality.
                </p>
                <button type="button" className="profile-mini-nav-link" onClick={() => setActiveSection("resume")}>Create or update resume</button>
              </div>

              <nav className="profile-nav-list" aria-label="Profile sections">
                {sectionList.map((section) => {
                  const Icon = section.icon;
                  const isActive = activeSection === section.key;
                  const completed = sectionCompletion[section.key];

                  return (
                    <button
                      key={section.key}
                      type="button"
                      className={`profile-nav-item ${isActive ? "active" : ""}`}
                      onClick={() => setActiveSection(section.key)}
                    >
                      <div className="profile-nav-main">
                        <div className="profile-nav-label-line">
                          {completed ? <CheckCircle2 size={16} color="#16a34a" /> : <Circle size={16} />}
                          <Icon size={15} />
                          <span>{section.label}</span>
                        </div>
                        {section.required ? <span className="profile-required-badge">Required</span> : null}
                      </div>
                      <small>{section.description}</small>
                    </button>
                  );
                })}
              </nav>
            </aside>

            <section className="profile-section-panel">{renderActiveSection()}</section>
          </div>
        </section>
      </main>
    </div>
  );
}
