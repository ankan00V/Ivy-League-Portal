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

type AccountType = "candidate" | "employer";
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

const SECTION_ITEMS: SectionMeta[] = [
  { key: "basic", label: "Basic Details", description: "Identity and account setup", icon: UserRound, requiredCandidate: true, requiredEmployer: true },
  { key: "resume", label: "Resume", description: "Upload and manage CV", icon: FileText, requiredCandidate: true },
  { key: "about", label: "About", description: "Short professional summary", icon: NotebookPen, requiredCandidate: true },
  { key: "skills", label: "Skills", description: "Skills and interests", icon: Sparkles, requiredCandidate: true },
  { key: "education", label: "Education", description: "Academic information", icon: GraduationCap, requiredCandidate: true },
  { key: "work", label: "Work Experience", description: "Role and experience", icon: BriefcaseBusiness },
  { key: "accomplishments", label: "Accomplishments & Initiatives", description: "Projects and achievements", icon: Award },
  { key: "personal", label: "Personal Details", description: "Address and personal info", icon: MapPinned },
  { key: "social", label: "Social Links", description: "External profile links", icon: Link2 },
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
      SECTION_ITEMS.map((section) => ({
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
          value={profile.account_type === "candidate" ? "Candidate" : "Employer"}
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

  const renderEducationSection = () => (
    <>
      {renderSectionHeader("Education", "Academic background and qualifications")}
      <div className="profile-field-grid two">
        {isStudentUniversityFlow
          ? renderUniversityField("Institution", "Type your university name manually")
          : (
              <TextField
                wrapperClassName="profile-field"
                label="Institution"
                value={profile.college_name}
                onChange={(event) => updateProfile("college_name", event.target.value)}
                placeholder="College / University"
              />
            )}
        {renderCourseField()}
      </div>
      <TextareaField
        wrapperClassName="profile-field"
        label="Education Details"
        rows={6}
        value={profile.education}
        onChange={(event) => updateProfile("education", event.target.value)}
        placeholder="Include major highlights: CGPA, thesis, coursework, and relevant milestones."
      />
    </>
  );

  const renderWorkSection = () => (
    <>
      {renderSectionHeader("Work Experience", "Role details and summary of your work")}
      <div className="profile-field-grid two">
        <TextField
          wrapperClassName="profile-field"
          label="Current Job Role"
          value={profile.current_job_role}
          onChange={(event) => updateProfile("current_job_role", event.target.value)}
          placeholder="IT Analyst / SDE Intern / Product Intern"
        />
        <TextField
          wrapperClassName="profile-field"
          label="Total Work Experience"
          value={profile.total_work_experience}
          onChange={(event) => updateProfile("total_work_experience", event.target.value)}
          placeholder="6 months / 1.5 years"
        />
      </div>
      <TextareaField
        wrapperClassName="profile-field"
        label="Experience Summary"
        rows={6}
        value={profile.experience_summary}
        onChange={(event) => updateProfile("experience_summary", event.target.value)}
        placeholder="Describe impact, ownership, tools used, and outcomes."
      />
    </>
  );

  const renderAccomplishmentsSection = () => (
    <>
      {renderSectionHeader("Accomplishments & Initiatives", "Certifications, projects, and leadership initiatives")}
      <div className="profile-field-grid two">
        <TextareaField
          wrapperClassName="profile-field"
          label="Achievements"
          rows={5}
          value={profile.achievements}
          onChange={(event) => updateProfile("achievements", event.target.value)}
          placeholder="Scholarships, competition ranks, notable wins"
        />
        <TextareaField
          wrapperClassName="profile-field"
          label="Certificates"
          rows={5}
          value={profile.certificates}
          onChange={(event) => updateProfile("certificates", event.target.value)}
          placeholder="Certifications from Oracle, Cisco, Coursera, etc."
        />
      </div>

      <div className="profile-field-grid two">
        <TextareaField
          wrapperClassName="profile-field"
          label="Projects"
          rows={5}
          value={profile.projects}
          onChange={(event) => updateProfile("projects", event.target.value)}
          placeholder="Major projects with short outcomes"
        />
        <TextareaField
          wrapperClassName="profile-field"
          label="Responsibilities / Initiatives"
          rows={5}
          value={profile.responsibilities}
          onChange={(event) => updateProfile("responsibilities", event.target.value)}
          placeholder="Leadership positions, clubs, volunteering, mentoring"
        />
      </div>
    </>
  );

  const renderPersonalSection = () => (
    <>
      {renderSectionHeader("Personal Details", "Where you are based, and your personal interests")}

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
              <Link href={profile.account_type === "employer" ? "/employer/dashboard" : "/dashboard"} className="btn-secondary">
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
