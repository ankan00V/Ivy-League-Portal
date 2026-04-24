"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";
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
import Sidebar from "@/components/Sidebar";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

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

type UserPayload = {
  email?: string;
};

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
  preferred_roles: string;
  preferred_locations: string;
  pan_india: boolean;
  prefer_wfh: boolean;
  consent_data_processing: boolean;
  consent_updates: boolean;
  bio: string;
  skills: string;
  interests: string;
  achievements: string;
  education: string;
  certificates: string;
  projects: string;
  responsibilities: string;
  gender: string;
  pronouns: string;
  date_of_birth: string;
  current_address_line1: string;
  current_address_landmark: string;
  current_address_region: string;
  current_address_pincode: string;
  permanent_address_line1: string;
  permanent_address_landmark: string;
  permanent_address_region: string;
  permanent_address_pincode: string;
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
  preferred_roles?: string;
  preferred_locations?: string;
  pan_india: boolean;
  prefer_wfh: boolean;
  consent_data_processing: boolean;
  consent_updates: boolean;
  bio?: string;
  skills?: string;
  interests?: string;
  achievements?: string;
  education?: string;
  certificates?: string;
  projects?: string;
  responsibilities?: string;
  gender?: string;
  pronouns?: string;
  date_of_birth?: string;
  current_address_line1?: string;
  current_address_landmark?: string;
  current_address_region?: string;
  current_address_pincode?: string;
  permanent_address_line1?: string;
  permanent_address_landmark?: string;
  permanent_address_region?: string;
  permanent_address_pincode?: string;
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
const PRONOUN_OPTIONS = ["He/Him", "She/Her", "They/Them", "Prefer not to say"];
const GENDER_OPTIONS = ["Male", "Female", "Non-binary", "Prefer not to say"];

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
    preferred_roles: toText(profilePayload.preferred_roles),
    preferred_locations: toText(profilePayload.preferred_locations),
    pan_india: Boolean(profilePayload.pan_india),
    prefer_wfh: Boolean(profilePayload.prefer_wfh),
    consent_data_processing: Boolean(profilePayload.consent_data_processing),
    consent_updates: Boolean(profilePayload.consent_updates),
    bio: toText(profilePayload.bio),
    skills: toText(profilePayload.skills),
    interests: toText(profilePayload.interests),
    achievements: toText(profilePayload.achievements),
    education: toText(profilePayload.education),
    certificates: toText(profilePayload.certificates),
    projects: toText(profilePayload.projects),
    responsibilities: toText(profilePayload.responsibilities),
    gender: toText(profilePayload.gender),
    pronouns: toText(profilePayload.pronouns),
    date_of_birth: toText(profilePayload.date_of_birth),
    current_address_line1: toText(profilePayload.current_address_line1),
    current_address_landmark: toText(profilePayload.current_address_landmark),
    current_address_region: toText(profilePayload.current_address_region),
    current_address_pincode: toText(profilePayload.current_address_pincode),
    permanent_address_line1: toText(profilePayload.permanent_address_line1),
    permanent_address_landmark: toText(profilePayload.permanent_address_landmark),
    permanent_address_region: toText(profilePayload.permanent_address_region),
    permanent_address_pincode: toText(profilePayload.permanent_address_pincode),
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
  assignOptionalText(payload, "bio", profile.bio);
  assignOptionalText(payload, "skills", profile.skills);
  assignOptionalText(payload, "interests", profile.interests);
  assignOptionalText(payload, "achievements", profile.achievements);
  assignOptionalText(payload, "education", profile.education);
  assignOptionalText(payload, "certificates", profile.certificates);
  assignOptionalText(payload, "projects", profile.projects);
  assignOptionalText(payload, "responsibilities", profile.responsibilities);
  assignOptionalText(payload, "gender", profile.gender);
  assignOptionalText(payload, "pronouns", profile.pronouns);
  assignOptionalText(payload, "date_of_birth", profile.date_of_birth);
  assignOptionalText(payload, "current_address_line1", profile.current_address_line1);
  assignOptionalText(payload, "current_address_landmark", profile.current_address_landmark);
  assignOptionalText(payload, "current_address_region", profile.current_address_region);
  assignOptionalText(payload, "current_address_pincode", profile.current_address_pincode);
  assignOptionalText(payload, "permanent_address_line1", profile.permanent_address_line1);
  assignOptionalText(payload, "permanent_address_landmark", profile.permanent_address_landmark);
  assignOptionalText(payload, "permanent_address_region", profile.permanent_address_region);
  assignOptionalText(payload, "permanent_address_pincode", profile.permanent_address_pincode);

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

export default function ProfilePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingResume, setUploadingResume] = useState(false);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("basic");
  const [copyCurrentAddress, setCopyCurrentAddress] = useState(false);
  const [hobbyInput, setHobbyInput] = useState("");

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
    preferred_roles: "",
    preferred_locations: "",
    pan_india: false,
    prefer_wfh: false,
    consent_data_processing: false,
    consent_updates: false,
    bio: "",
    skills: "",
    interests: "",
    achievements: "",
    education: "",
    certificates: "",
    projects: "",
    responsibilities: "",
    gender: "",
    pronouns: "",
    date_of_birth: "",
    current_address_line1: "",
    current_address_landmark: "",
    current_address_region: "",
    current_address_pincode: "",
    permanent_address_line1: "",
    permanent_address_landmark: "",
    permanent_address_region: "",
    permanent_address_pincode: "",
    hobbies: [],
    social_links: {},
    resume_url: "",
    resume_filename: "",
    resume_content_type: "",
    resume_uploaded_at: "",
  });

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    const loadProfile = async (showFatalErrors: boolean) => {
      try {
        const [userResult, profileResult] = await Promise.allSettled([
          fetch(apiUrl("/api/v1/users/me"), { headers: { Authorization: `Bearer ${token}` } }),
          fetch(apiUrl("/api/v1/users/me/profile"), { headers: { Authorization: `Bearer ${token}` } }),
        ]);

        let userError: string | null = null;
        let profileError: string | null = null;
        let hasFreshProfile = false;

        if (userResult.status === "fulfilled") {
          const userRes = userResult.value;
          const userPayload = (await userRes.json().catch(() => ({}))) as UserPayload | Record<string, unknown>;
          if (userRes.ok) {
            setEmail(toText(userPayload.email));
          } else if (showFatalErrors) {
            userError = getApiErrorMessage(userPayload, "Unable to load user details");
          }
        } else if (showFatalErrors) {
          userError = getUnknownErrorMessage(userResult.reason, "Unable to load user details");
        }

        if (profileResult.status === "fulfilled") {
          const profileRes = profileResult.value;
          const profilePayload = (await profileRes.json().catch(() => ({}))) as Record<string, unknown>;
          if (profileRes.ok) {
            const nextProfile = hydrateProfilePayload(profilePayload);
            setProfile(nextProfile);
            hasFreshProfile = true;
            setError(null);
            setCopyCurrentAddress(
              hasText(nextProfile.current_address_line1) &&
                nextProfile.current_address_line1 === nextProfile.permanent_address_line1 &&
                nextProfile.current_address_landmark === nextProfile.permanent_address_landmark &&
                nextProfile.current_address_region === nextProfile.permanent_address_region &&
                nextProfile.current_address_pincode === nextProfile.permanent_address_pincode
            );
          } else if (showFatalErrors) {
            profileError = getApiErrorMessage(profilePayload, "Unable to load profile");
          }
        } else if (showFatalErrors) {
          profileError = getUnknownErrorMessage(profileResult.reason, "Unable to load profile");
        }

        if (!showFatalErrors) {
          return;
        }

        if (profileError) {
          setError(profileError);
          return;
        }

        if (!hasFreshProfile && userError) {
          setError(userError);
          return;
        }

        setError(null);
      } catch (err) {
        if (showFatalErrors) {
          setError(getUnknownErrorMessage(err, "Unable to load profile"));
        }
      } finally {
        setLoading(false);
      }
    };

    void loadProfile(true);

    const handleWindowFocus = () => {
      void loadProfile(false);
    };

    window.addEventListener("focus", handleWindowFocus);
    return () => {
      window.removeEventListener("focus", handleWindowFocus);
    };
  }, [router]);

  useEffect(() => {
    if (!copyCurrentAddress) {
      return;
    }
    setProfile((prev) => {
      const nextPermanentLine1 = prev.current_address_line1;
      const nextPermanentLandmark = prev.current_address_landmark;
      const nextPermanentRegion = prev.current_address_region;
      const nextPermanentPincode = prev.current_address_pincode;

      if (
        prev.permanent_address_line1 === nextPermanentLine1 &&
        prev.permanent_address_landmark === nextPermanentLandmark &&
        prev.permanent_address_region === nextPermanentRegion &&
        prev.permanent_address_pincode === nextPermanentPincode
      ) {
        return prev;
      }

      return {
        ...prev,
        permanent_address_line1: nextPermanentLine1,
        permanent_address_landmark: nextPermanentLandmark,
        permanent_address_region: nextPermanentRegion,
        permanent_address_pincode: nextPermanentPincode,
      };
    });
  }, [copyCurrentAddress, profile.current_address_line1, profile.current_address_landmark, profile.current_address_region, profile.current_address_pincode]);

  const updateProfile = <K extends keyof ProfilePayload>(field: K, value: ProfilePayload[K]) => {
    setProfile((prev) => ({ ...prev, [field]: value }));
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
    const exists = profile.hobbies.some((item) => item.toLowerCase() === cleaned.toLowerCase());
    if (!exists) {
      updateProfile("hobbies", [...profile.hobbies, cleaned]);
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

  const saveProfile = async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const payloadToSave = buildProfileUpdatePayload(profile);
      const res = await fetch(apiUrl("/api/v1/users/me/profile"), {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payloadToSave),
      });
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update profile"));
      }
      setProfile(hydrateProfilePayload(payload));
      setMessage("Profile updated successfully.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to update profile"));
    } finally {
      setSaving(false);
    }
  };

  const uploadResume = async (file: File) => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setUploadingResume(true);
    setMessage(null);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(apiUrl("/api/v1/users/me/resume"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: form,
      });
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to upload resume"));
      }
      setProfile(hydrateProfilePayload(payload));
      setMessage("Resume uploaded and profile signals refreshed.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to upload resume"));
    } finally {
      setUploadingResume(false);
    }
  };

  const deleteResume = async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setUploadingResume(true);
    setMessage(null);
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/v1/users/me/resume"), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to remove resume"));
      }
      setProfile(hydrateProfilePayload(payload));
      setMessage("Resume removed.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to remove resume"));
    } finally {
      setUploadingResume(false);
    }
  };

  const downloadResume = async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/v1/users/me/resume/download"), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(getApiErrorMessage(payload, "Unable to download resume"));
      }
      const blob = await res.blob();
      const link = document.createElement("a");
      const objectUrl = URL.createObjectURL(blob);
      link.href = objectUrl;
      link.download = profile.resume_filename || "resume";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to download resume"));
    }
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
      personal: hasText(profile.date_of_birth) || hasText(profile.current_address_line1) || profile.hobbies.length > 0,
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

  const renderBasicSection = () => (
    <>
      {renderSectionHeader("Basic Details", "Identity, user type, and role preferences")}

      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>First Name *</label>
          <input className="input-base" value={profile.first_name} onChange={(event) => updateProfile("first_name", event.target.value)} placeholder="First name" />
        </div>
        <div className="profile-field">
          <label>Last Name</label>
          <input className="input-base" value={profile.last_name} onChange={(event) => updateProfile("last_name", event.target.value)} placeholder="Last name" />
        </div>
      </div>

      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Email</label>
          <input className="input-base" value={email} disabled />
        </div>
        <div className="profile-field">
          <label>Account Type</label>
          <input className="input-base" value={profile.account_type === "candidate" ? "Candidate" : "Employer"} disabled />
        </div>
      </div>

      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Country Code</label>
          <input className="input-base" value={profile.country_code} onChange={(event) => updateProfile("country_code", event.target.value)} placeholder="+91" />
        </div>
        <div className="profile-field">
          <label>Mobile *</label>
          <input className="input-base" value={profile.mobile} onChange={(event) => updateProfile("mobile", event.target.value)} placeholder="Enter mobile number" />
        </div>
      </div>

      {isCandidate ? (
        <>
          <div className="profile-field">
            <label>User Type *</label>
            <div className="profile-pill-row">
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
            </div>
          </div>

          <div className="profile-field">
            <label>Domain</label>
            <div className="profile-pill-row">
              {DOMAIN_OPTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`profile-pill ${profile.domain === item ? "active" : ""}`}
                  onClick={() => updateProfile("domain", item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Course</label>
              <input className="input-base" value={profile.course} onChange={(event) => updateProfile("course", event.target.value)} placeholder="B.Tech / MBA / BA ..." />
            </div>
            <div className="profile-field">
              <label>Course Specialization</label>
              <input
                className="input-base"
                value={profile.course_specialization}
                onChange={(event) => updateProfile("course_specialization", event.target.value)}
                placeholder="Computer Science / Finance / Marketing ..."
              />
            </div>
          </div>

          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Passout Year</label>
              <input
                className="input-base"
                type="number"
                value={profile.passout_year ?? ""}
                onChange={(event) => updateProfile("passout_year", event.target.value ? Number(event.target.value) : null)}
                placeholder="2027"
              />
            </div>
            <div className="profile-field">
              <label>Class / Grade</label>
              <input
                className="input-base"
                type="number"
                value={profile.class_grade ?? ""}
                onChange={(event) => updateProfile("class_grade", event.target.value ? Number(event.target.value) : null)}
                placeholder="12"
              />
            </div>
          </div>

          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Current Role</label>
              <input
                className="input-base"
                value={profile.current_job_role}
                onChange={(event) => updateProfile("current_job_role", event.target.value)}
                placeholder="Student / Analyst / Developer"
              />
            </div>
            <div className="profile-field">
              <label>Total Work Experience</label>
              <input
                className="input-base"
                value={profile.total_work_experience}
                onChange={(event) => updateProfile("total_work_experience", event.target.value)}
                placeholder="0-1 years"
              />
            </div>
          </div>

          <div className="profile-field">
            <label>College / University</label>
            <input
              className="input-base"
              value={profile.college_name}
              onChange={(event) => updateProfile("college_name", event.target.value)}
              placeholder="Your institute name"
            />
          </div>

          <div className="profile-field">
            <label>Purpose / Goals</label>
            <div className="profile-pill-row">
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
            </div>
          </div>

          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Preferred Roles</label>
              <input
                className="input-base"
                value={profile.preferred_roles}
                onChange={(event) => updateProfile("preferred_roles", event.target.value)}
                placeholder="Data Scientist, Software Engineer"
              />
            </div>
            <div className="profile-field">
              <label>Preferred Work Locations</label>
              <input
                className="input-base"
                value={profile.preferred_locations}
                onChange={(event) => updateProfile("preferred_locations", event.target.value)}
                placeholder="Bangalore, Hyderabad, Remote"
              />
            </div>
          </div>

          <div className="profile-inline-group">
            <label className="profile-inline-check">
              <input type="checkbox" checked={profile.pan_india} onChange={(event) => updateProfile("pan_india", event.target.checked)} />
              Open to opportunities across India
            </label>
            <label className="profile-inline-check">
              <input type="checkbox" checked={profile.prefer_wfh} onChange={(event) => updateProfile("prefer_wfh", event.target.checked)} />
              Prefer work from home
            </label>
          </div>
        </>
      ) : (
        <>
          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Company Name *</label>
              <input
                className="input-base"
                value={profile.company_name}
                onChange={(event) => updateProfile("company_name", event.target.value)}
                placeholder="Your organization"
              />
            </div>
            <div className="profile-field">
              <label>Current Role</label>
              <input
                className="input-base"
                value={profile.current_job_role}
                onChange={(event) => updateProfile("current_job_role", event.target.value)}
                placeholder="Founder / Recruiter / HR"
              />
            </div>
          </div>

          <div className="profile-field-grid two">
            <div className="profile-field">
              <label>Company Website</label>
              <input
                className="input-base"
                value={profile.company_website}
                onChange={(event) => updateProfile("company_website", event.target.value)}
                placeholder="https://company.com"
              />
            </div>
            <div className="profile-field">
              <label>Company Size</label>
              <input
                className="input-base"
                value={profile.company_size}
                onChange={(event) => updateProfile("company_size", event.target.value)}
                placeholder="11-50"
              />
            </div>
          </div>

          <div className="profile-field">
            <label>Hiring For *</label>
            <div className="profile-pill-row">
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
            </div>
          </div>
        </>
      )}

      <div className="profile-inline-group">
        <label className="profile-inline-check">
          <input
            type="checkbox"
            checked={profile.consent_data_processing}
            onChange={(event) => updateProfile("consent_data_processing", event.target.checked)}
          />
          I agree to data processing and privacy terms *
        </label>
        <label className="profile-inline-check">
          <input type="checkbox" checked={profile.consent_updates} onChange={(event) => updateProfile("consent_updates", event.target.checked)} />
          I want product and opportunity updates
        </label>
      </div>
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

        <label className="btn-primary profile-upload-btn" style={{ opacity: uploadingResume ? 0.7 : 1 }}>
          <Upload size={15} /> {uploadingResume ? "Uploading..." : profile.resume_filename ? "Replace Resume" : "Upload Resume"}
          <input
            type="file"
            accept=".txt,.pdf,.doc,.docx"
            disabled={uploadingResume}
            style={{ display: "none" }}
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
      </div>
    </>
  );

  const renderAboutSection = () => (
    <>
      {renderSectionHeader("About", "Introduce yourself in a concise, professional way")}
      <div className="profile-field">
        <label>{isCandidate ? "About Me" : "Company Description"} {isCandidate ? "*" : ""}</label>
        <textarea
          className="input-base"
          rows={7}
          value={isCandidate ? profile.bio : profile.company_description}
          onChange={(event) => (isCandidate ? updateProfile("bio", event.target.value) : updateProfile("company_description", event.target.value))}
          placeholder={
            isCandidate
              ? "Write a short profile summary (career goals, strengths, and interests)."
              : "Tell candidates what your organization does and what opportunities you offer."
          }
        />
      </div>
    </>
  );

  const renderSkillsSection = () => (
    <>
      {renderSectionHeader("Skills", "Highlight your skills and areas of interest")}
      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Skills *</label>
          <textarea
            className="input-base"
            rows={5}
            value={profile.skills}
            onChange={(event) => updateProfile("skills", event.target.value)}
            placeholder="Python, Data Analysis, C++, SQL, Communication"
          />
          {splitCommaValues(profile.skills).length > 0 ? (
            <div className="profile-tag-row">
              {splitCommaValues(profile.skills).map((skill) => (
                <span key={skill} className="profile-tag">
                  {skill}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="profile-field">
          <label>Interests</label>
          <textarea
            className="input-base"
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
        <div className="profile-field">
          <label>Institution</label>
          <input
            className="input-base"
            value={profile.college_name}
            onChange={(event) => updateProfile("college_name", event.target.value)}
            placeholder="College / University"
          />
        </div>
        <div className="profile-field">
          <label>Course</label>
          <input className="input-base" value={profile.course} onChange={(event) => updateProfile("course", event.target.value)} placeholder="Degree or course" />
        </div>
      </div>
      <div className="profile-field">
        <label>Education Details</label>
        <textarea
          className="input-base"
          rows={6}
          value={profile.education}
          onChange={(event) => updateProfile("education", event.target.value)}
          placeholder="Include major highlights: CGPA, thesis, coursework, and relevant milestones."
        />
      </div>
    </>
  );

  const renderWorkSection = () => (
    <>
      {renderSectionHeader("Work Experience", "Role details and summary of your work")}
      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Current Job Role</label>
          <input
            className="input-base"
            value={profile.current_job_role}
            onChange={(event) => updateProfile("current_job_role", event.target.value)}
            placeholder="IT Analyst / SDE Intern / Product Intern"
          />
        </div>
        <div className="profile-field">
          <label>Total Work Experience</label>
          <input
            className="input-base"
            value={profile.total_work_experience}
            onChange={(event) => updateProfile("total_work_experience", event.target.value)}
            placeholder="6 months / 1.5 years"
          />
        </div>
      </div>
      <div className="profile-field">
        <label>Experience Summary</label>
        <textarea
          className="input-base"
          rows={6}
          value={profile.experience_summary}
          onChange={(event) => updateProfile("experience_summary", event.target.value)}
          placeholder="Describe impact, ownership, tools used, and outcomes."
        />
      </div>
    </>
  );

  const renderAccomplishmentsSection = () => (
    <>
      {renderSectionHeader("Accomplishments & Initiatives", "Certifications, projects, and leadership initiatives")}
      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Achievements</label>
          <textarea
            className="input-base"
            rows={5}
            value={profile.achievements}
            onChange={(event) => updateProfile("achievements", event.target.value)}
            placeholder="Scholarships, competition ranks, notable wins"
          />
        </div>
        <div className="profile-field">
          <label>Certificates</label>
          <textarea
            className="input-base"
            rows={5}
            value={profile.certificates}
            onChange={(event) => updateProfile("certificates", event.target.value)}
            placeholder="Certifications from Oracle, Cisco, Coursera, etc."
          />
        </div>
      </div>

      <div className="profile-field-grid two">
        <div className="profile-field">
          <label>Projects</label>
          <textarea
            className="input-base"
            rows={5}
            value={profile.projects}
            onChange={(event) => updateProfile("projects", event.target.value)}
            placeholder="Major projects with short outcomes"
          />
        </div>
        <div className="profile-field">
          <label>Responsibilities / Initiatives</label>
          <textarea
            className="input-base"
            rows={5}
            value={profile.responsibilities}
            onChange={(event) => updateProfile("responsibilities", event.target.value)}
            placeholder="Leadership positions, clubs, volunteering, mentoring"
          />
        </div>
      </div>
    </>
  );

  const renderPersonalSection = () => (
    <>
      {renderSectionHeader("Personal Details", "Pronouns, DOB, address, and personal interests")}
      <div className="profile-field">
        <label>Pronouns</label>
        <div className="profile-pill-row">
          {PRONOUN_OPTIONS.map((item) => (
            <button
              key={item}
              type="button"
              className={`profile-pill ${profile.pronouns === item ? "active" : ""}`}
              onClick={() => updateProfile("pronouns", item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="profile-field">
        <label>Gender</label>
        <div className="profile-pill-row">
          {GENDER_OPTIONS.map((item) => (
            <button key={item} type="button" className={`profile-pill ${profile.gender === item ? "active" : ""}`} onClick={() => updateProfile("gender", item)}>
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="profile-field">
        <label>Date of Birth</label>
        <input
          className="input-base"
          value={profile.date_of_birth}
          onChange={(event) => updateProfile("date_of_birth", event.target.value)}
          placeholder="YYYY-MM-DD or DD/MM/YYYY"
        />
      </div>

      <div className="profile-address-card">
        <h3>Current Address</h3>
        <div className="profile-field-grid two">
          <div className="profile-field">
            <label>Address Line 1</label>
            <input
              className="input-base"
              value={profile.current_address_line1}
              onChange={(event) => updateProfile("current_address_line1", event.target.value)}
              placeholder="Street, locality"
            />
          </div>
          <div className="profile-field">
            <label>Landmark</label>
            <input
              className="input-base"
              value={profile.current_address_landmark}
              onChange={(event) => updateProfile("current_address_landmark", event.target.value)}
              placeholder="Landmark"
            />
          </div>
        </div>
        <div className="profile-field-grid two">
          <div className="profile-field">
            <label>City / Region</label>
            <input
              className="input-base"
              value={profile.current_address_region}
              onChange={(event) => updateProfile("current_address_region", event.target.value)}
              placeholder="City, State, Country"
            />
          </div>
          <div className="profile-field">
            <label>Pincode</label>
            <input
              className="input-base"
              value={profile.current_address_pincode}
              onChange={(event) => updateProfile("current_address_pincode", event.target.value)}
              placeholder="144411"
            />
          </div>
        </div>
      </div>

      <div className="profile-address-card">
        <div className="profile-address-head">
          <h3>Permanent Address</h3>
          <label className="profile-inline-check">
            <input type="checkbox" checked={copyCurrentAddress} onChange={(event) => setCopyCurrentAddress(event.target.checked)} />
            Copy current address
          </label>
        </div>

        <div className="profile-field-grid two">
          <div className="profile-field">
            <label>Address Line 1</label>
            <input
              className="input-base"
              value={profile.permanent_address_line1}
              onChange={(event) => updateProfile("permanent_address_line1", event.target.value)}
              placeholder="Street, locality"
            />
          </div>
          <div className="profile-field">
            <label>Landmark</label>
            <input
              className="input-base"
              value={profile.permanent_address_landmark}
              onChange={(event) => updateProfile("permanent_address_landmark", event.target.value)}
              placeholder="Landmark"
            />
          </div>
        </div>

        <div className="profile-field-grid two">
          <div className="profile-field">
            <label>City / Region</label>
            <input
              className="input-base"
              value={profile.permanent_address_region}
              onChange={(event) => updateProfile("permanent_address_region", event.target.value)}
              placeholder="City, State, Country"
            />
          </div>
          <div className="profile-field">
            <label>Pincode</label>
            <input
              className="input-base"
              value={profile.permanent_address_pincode}
              onChange={(event) => updateProfile("permanent_address_pincode", event.target.value)}
              placeholder="713358"
            />
          </div>
        </div>
      </div>

      <div className="profile-field">
        <label>Hobbies</label>
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
      </div>
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
            <div key={field.key} className="profile-field">
              <label>{field.label}</label>
              <input
                className="input-base"
                value={profile.social_links[field.key] || ""}
                onChange={(event) => updateSocialLink(field.key, event.target.value)}
                placeholder={field.placeholder}
              />
            </div>
          ))}

          {extraSocialEntries.map(([key, value]) => (
            <div key={key} className="profile-field">
              <label>{key.replace(/_/g, " ")}</label>
              <input className="input-base" value={value} onChange={(event) => updateSocialLink(key, event.target.value)} placeholder="https://..." />
            </div>
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
      <div style={{ minHeight: "100vh", display: "flex", background: "var(--bg-base)" }}>
        <Sidebar />
        <main className="main-content">
          <CenteredPageSkeleton paneHeight="700px" />
        </main>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", background: "var(--bg-base)" }}>
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
