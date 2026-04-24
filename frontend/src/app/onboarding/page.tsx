"use client";

import Image from "next/image";
import React, { useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { CenteredPageSkeleton } from "@/components/LoadingSkeletons";
import FieldGrid from "@/components/ui/FieldGrid";
import FormSection from "@/components/ui/FormSection";
import PillGroup from "@/components/ui/PillGroup";
import ToggleRow from "@/components/ui/ToggleRow";
import { useOnboardingFlow } from "@/hooks/useOnboardingFlow";
import { INDIAN_INSTITUTION_OPTIONS, OTHER_INSTITUTION_LABEL } from "@/lib/indian-institutions";

type AccountType = "candidate" | "employer";
type UserType = "school_student" | "college_student" | "fresher" | "professional";

type ProfilePayload = {
  account_type: AccountType;
  first_name: string;
  last_name: string;
  mobile: string;
  country_code: string;
  user_type: UserType | "";
  domain: string;
  course: string;
  passout_year: number | null;
  class_grade: number | null;
  current_job_role: string;
  total_work_experience: string;
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
  resume_url: string;
  resume_filename: string;
  resume_uploaded_at: string;
  bio: string;
  skills: string;
  interests: string;
  achievements: string;
  education: string;
};

type OnboardingStatus = {
  completed: boolean;
  progress_percent: number;
  missing_fields: string[];
  recommended_next_step: string;
};

type OnboardingUpdatePayload = {
  account_type: AccountType;
  first_name: string;
  last_name: string;
  mobile: string;
  country_code: string;
  user_type?: UserType;
  domain?: string;
  course?: string;
  passout_year?: number | null;
  class_grade?: number | null;
  current_job_role?: string;
  total_work_experience?: string;
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
};

const DOMAIN_OPTIONS = ["Management", "Engineering", "Arts & Science", "Medicine", "Law"];
const GOAL_OPTIONS = ["To find a Job", "Compete & Upskill", "To Host an Event", "To be a Mentor"];
const EXPERIENCE_OPTIONS = ["0-1 years", "1-3 years", "3-5 years", "5+ years"];
const EMPLOYER_ROLE_OPTIONS = [
  "Recruiting Coordinator",
  "Recruitment Manager",
  "Recruitment Specialist",
  "CEO",
  "Other",
];
const EMPLOYER_ORGANIZATION_SUGGESTIONS = [
  "Tata Consultancy Services",
  "Infosys",
  "Wipro",
  "HCLTech",
  "Accenture India",
  "Lovely Professional University (LPU)",
  "IIT Bombay",
  "Indian Institute of Science (IISc)",
];
const DEFAULT_YEARS = [2026, 2027, 2028, 2029, 2030, 2031];
const SCHOOL_GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
const RESUME_REQUIRED_USER_TYPES = new Set<UserType>(["college_student", "fresher", "professional"]);
const OTHER_UNIVERSITY_VALUE = "__other__";
const UNIVERSITY_OPTION_VALUES = new Set<string>(INDIAN_INSTITUTION_OPTIONS.map((item) => item.label));
const UNIVERSITY_OPTIONS = Array.from(UNIVERSITY_OPTION_VALUES);

const ONBOARDING_VISUALS = [
  "https://images.unsplash.com/photo-1529074963764-98f45c47344b?auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=1200&q=80",
];

function pillButtonClass(active: boolean): string {
  return `vv-pill-button${active ? " active" : ""}`;
}

type OptionalStringFieldKey =
  | "domain"
  | "course"
  | "current_job_role"
  | "total_work_experience"
  | "college_name"
  | "company_name"
  | "company_website"
  | "company_size"
  | "company_description"
  | "preferred_roles"
  | "preferred_locations"
  | "bio"
  | "skills"
  | "interests"
  | "achievements"
  | "education";

function withOptionalString(target: OnboardingUpdatePayload, key: OptionalStringFieldKey, value: string) {
  const trimmed = value.trim();
  if (trimmed.length > 0) {
    target[key] = trimmed;
  }
}

function deriveUniversitySelection(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  return UNIVERSITY_OPTION_VALUES.has(trimmed) ? trimmed : OTHER_UNIVERSITY_VALUE;
}

function buildOnboardingPayload(profile: ProfilePayload): OnboardingUpdatePayload {
  const payload: OnboardingUpdatePayload = {
    account_type: profile.account_type,
    first_name: profile.first_name.trim(),
    last_name: profile.last_name.trim(),
    mobile: profile.mobile.trim(),
    country_code: profile.country_code.trim() || "+91",
    pan_india: profile.pan_india,
    prefer_wfh: profile.prefer_wfh,
    consent_data_processing: profile.consent_data_processing,
    consent_updates: profile.consent_updates,
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
  if (profile.goals.length > 0) {
    payload.goals = [...profile.goals];
  }

  withOptionalString(payload, "domain", profile.domain);
  withOptionalString(payload, "course", profile.course);
  withOptionalString(payload, "current_job_role", profile.current_job_role);
  withOptionalString(payload, "total_work_experience", profile.total_work_experience);
  withOptionalString(payload, "college_name", profile.college_name);
  withOptionalString(payload, "company_name", profile.company_name);
  withOptionalString(payload, "company_website", profile.company_website);
  withOptionalString(payload, "company_size", profile.company_size);
  withOptionalString(payload, "company_description", profile.company_description);
  withOptionalString(payload, "preferred_roles", profile.preferred_roles);
  withOptionalString(payload, "preferred_locations", profile.preferred_locations);
  withOptionalString(payload, "bio", profile.bio ?? "");
  withOptionalString(payload, "skills", profile.skills ?? "");
  withOptionalString(payload, "interests", profile.interests ?? "");
  withOptionalString(payload, "achievements", profile.achievements ?? "");
  withOptionalString(payload, "education", profile.education ?? "");

  return payload;
}

function hydrateOnboardingProfilePayload(payload: Record<string, unknown>, previous: ProfilePayload): ProfilePayload {
  const asText = (value: unknown, fallback: string): string => (typeof value === "string" ? value : fallback);
  const asNullableNumber = (value: unknown, fallback: number | null): number | null => (typeof value === "number" ? value : fallback);
  const asBoolean = (key: keyof ProfilePayload, fallback: boolean): boolean =>
    Object.prototype.hasOwnProperty.call(payload, key) ? Boolean(payload[key]) : fallback;

  return {
    ...previous,
    account_type: (typeof payload.account_type === "string" ? payload.account_type : previous.account_type) as AccountType,
    first_name: asText(payload.first_name, previous.first_name),
    last_name: asText(payload.last_name, previous.last_name),
    mobile: asText(payload.mobile, previous.mobile),
    country_code: asText(payload.country_code, previous.country_code || "+91") || "+91",
    user_type: (typeof payload.user_type === "string" ? payload.user_type : previous.user_type) as UserType | "",
    domain: asText(payload.domain, previous.domain),
    course: asText(payload.course, previous.course),
    passout_year: asNullableNumber(payload.passout_year, previous.passout_year),
    class_grade: asNullableNumber(payload.class_grade, previous.class_grade),
    current_job_role: asText(payload.current_job_role, previous.current_job_role),
    total_work_experience: asText(payload.total_work_experience, previous.total_work_experience),
    college_name: asText(payload.college_name, previous.college_name),
    company_name: asText(payload.company_name, previous.company_name),
    company_website: asText(payload.company_website, previous.company_website),
    company_size: asText(payload.company_size, previous.company_size),
    company_description: asText(payload.company_description, previous.company_description),
    hiring_for: (typeof payload.hiring_for === "string" ? payload.hiring_for : previous.hiring_for) as "myself" | "others" | "",
    goals: Array.isArray(payload.goals) ? payload.goals.map((item) => String(item)) : previous.goals,
    preferred_roles: asText(payload.preferred_roles, previous.preferred_roles),
    preferred_locations: asText(payload.preferred_locations, previous.preferred_locations),
    pan_india: asBoolean("pan_india", previous.pan_india),
    prefer_wfh: asBoolean("prefer_wfh", previous.prefer_wfh),
    consent_data_processing: asBoolean("consent_data_processing", previous.consent_data_processing),
    consent_updates: asBoolean("consent_updates", previous.consent_updates),
    resume_url: asText(payload.resume_url, previous.resume_url),
    resume_filename: asText(payload.resume_filename, previous.resume_filename),
    resume_uploaded_at: asText(payload.resume_uploaded_at, previous.resume_uploaded_at),
    bio: asText(payload.bio, previous.bio),
    skills: asText(payload.skills, previous.skills),
    interests: asText(payload.interests, previous.interests),
    achievements: asText(payload.achievements, previous.achievements),
    education: asText(payload.education, previous.education),
  };
}

export default function OnboardingPage() {
  const [profile, setProfile] = useState<ProfilePayload>({
    account_type: "candidate",
    first_name: "",
    last_name: "",
    mobile: "",
    country_code: "+91",
    user_type: "",
    domain: "",
    course: "",
    passout_year: null,
    class_grade: null,
    current_job_role: "",
    total_work_experience: "",
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
    resume_url: "",
    resume_filename: "",
    resume_uploaded_at: "",
    bio: "",
    skills: "",
    interests: "",
    achievements: "",
    education: "",
  });
  const {
    loading,
    saving,
    step,
    setStep,
    error,
    resumeUploading,
    employerRoleSelection,
    setEmployerRoleSelection,
    selectedUniversity,
    setSelectedUniversity,
    status,
    handleResumeUpload,
    handleResumeDelete,
    handleSave,
    logout,
  } = useOnboardingFlow<ProfilePayload, OnboardingUpdatePayload, OnboardingStatus>({
    profile,
    setProfile,
    hydrateProfilePayload: hydrateOnboardingProfilePayload,
    buildOnboardingPayload,
    deriveUniversitySelection,
    employerRoleOptions: EMPLOYER_ROLE_OPTIONS,
    getAccountTypeFromProfile: (value) => value.account_type,
    getCollegeNameFromProfile: (value) => value.college_name,
    getCurrentRoleFromProfile: (value) => value.current_job_role,
    resolveRouteForAccountType: (accountType) => (accountType === "employer" ? "/employer/dashboard" : "/dashboard"),
  });

  const totalSteps = profile.account_type === "employer" ? 2 : 3;
  const visual = useMemo(() => ONBOARDING_VISUALS[(step - 1) % ONBOARDING_VISUALS.length], [step]);

  useEffect(() => {
    if (step > totalSteps) {
      setStep(totalSteps);
    }
  }, [setStep, step, totalSteps]);

  const missingConsent = !profile.consent_data_processing;
  const requiresUserType = profile.account_type === "candidate";
  const resumeRequiredForUserType =
    profile.account_type === "candidate" && profile.user_type.length > 0 && RESUME_REQUIRED_USER_TYPES.has(profile.user_type as UserType);
  const hasResume = profile.resume_url.trim().length > 0;
  const canContinueStep1 =
    profile.first_name.trim().length > 0 &&
    profile.mobile.trim().length >= 8 &&
    (!requiresUserType || profile.user_type.length > 0) &&
    !missingConsent;

  const canContinueStep2 = (() => {
    if (profile.account_type === "employer") {
      return (
        profile.company_name.trim().length > 0 &&
        profile.current_job_role.trim().length > 0 &&
        profile.hiring_for.length > 0
      );
    }
    if (profile.user_type === "school_student") {
      return profile.class_grade !== null;
    }
    if (profile.user_type === "college_student" || profile.user_type === "fresher") {
      return (
        profile.domain.trim().length > 0 &&
        profile.course.trim().length > 0 &&
        profile.passout_year !== null &&
        profile.college_name.trim().length > 0 &&
        (!resumeRequiredForUserType || hasResume)
      );
    }
    if (profile.user_type === "professional") {
      return (
        profile.current_job_role.trim().length > 0 &&
        profile.total_work_experience.trim().length > 0 &&
        (!resumeRequiredForUserType || hasResume)
      );
    }
    return false;
  })();

  const updateProfile = <K extends keyof ProfilePayload>(field: K, value: ProfilePayload[K]) => {
    setProfile((prev) => ({ ...prev, [field]: value }));
  };

  const toggleGoal = (goal: string) => {
    setProfile((prev) => {
      const exists = prev.goals.includes(goal);
      const goals = exists ? prev.goals.filter((item) => item !== goal) : [...prev.goals, goal];
      return { ...prev, goals };
    });
  };

  if (loading) {
    return <CenteredPageSkeleton paneHeight="760px" />;
  }

  return (
    <main className="onboarding-page-root">
      <section className="card-panel auth-shell onboarding-shell">
        <aside className="auth-left-pane onboarding-left-pane">
          <BrandLogo size="md" />
          <div className="onboarding-visual-frame">
            <Image
              src={visual}
              alt="Onboarding visual"
              fill
              sizes="(max-width: 1100px) 100vw, 50vw"
              className="onboarding-visual-image"
            />
          </div>
          <div>
            <h2 className="onboarding-hero-title">Set up your profile</h2>
            <p className="onboarding-hero-subtitle">
              We personalize recommendations and matching based on this setup.
            </p>
          </div>
        </aside>

        <div className="auth-right-pane onboarding-right-pane">
          <div>
            <h1 className="onboarding-page-title">You&apos;re almost there</h1>
            <div className="onboarding-progress-wrap">
              {Array.from({ length: totalSteps }, (_, idx) => idx + 1).map((n) => (
                <div
                  key={n}
                  className={`onboarding-progress-step ${n <= step ? "active" : "pending"}`}
                />
              ))}
              <span className="onboarding-progress-text">
                {status?.progress_percent ?? 0}% complete
              </span>
            </div>
          </div>

          {error && (
            <div className="onboarding-alert-error">
              {error}
            </div>
          )}

          <div className="onboarding-form-body">
            {step === 1 && (
              <>
                <FieldGrid variant="two">
                  <FormSection label="First Name">
                    <input className="input-base" value={profile.first_name} onChange={(e) => updateProfile("first_name", e.target.value)} />
                  </FormSection>
                  <FormSection label="Last Name">
                    <input className="input-base" value={profile.last_name} onChange={(e) => updateProfile("last_name", e.target.value)} />
                  </FormSection>
                </FieldGrid>

                <FieldGrid variant="leading-compact">
                  <FormSection label="Country Code">
                    <input className="input-base" value={profile.country_code} onChange={(e) => updateProfile("country_code", e.target.value)} />
                  </FormSection>
                  <FormSection label="Mobile">
                    <input className="input-base" value={profile.mobile} onChange={(e) => updateProfile("mobile", e.target.value)} placeholder="1234567890" />
                  </FormSection>
                </FieldGrid>

                <FormSection
                  label="Account Type"
                  labelSpaced
                  helper={profile.account_type === "employer" ? "Employer access is restricted to corporate email domains." : undefined}
                >
                  <div className="onboarding-account-type-chip">
                    <strong>{profile.account_type === "employer" ? "Employer" : "Candidate"}</strong>
                  </div>
                </FormSection>

                {profile.account_type === "candidate" && (
                  <FormSection label="User Type" labelSpaced>
                    <PillGroup>
                      {[
                        { key: "school_student", label: "School Student" },
                        { key: "college_student", label: "College Student" },
                        { key: "fresher", label: "Fresher" },
                        { key: "professional", label: "Educator / Professional" },
                      ].map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          className={pillButtonClass(profile.user_type === item.key)}
                          onClick={() => updateProfile("user_type", item.key as UserType)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </PillGroup>
                  </FormSection>
                )}

                <ToggleRow checked={profile.consent_data_processing} onChange={(checked) => updateProfile("consent_data_processing", checked)} align="start">
                  I agree to data processing and privacy policy.
                </ToggleRow>
                <ToggleRow checked={profile.consent_updates} onChange={(checked) => updateProfile("consent_updates", checked)} align="start">
                  Keep me updated with relevant opportunities.
                </ToggleRow>
              </>
            )}

            {step === 2 && (
              <>
                {profile.account_type === "candidate" && (profile.user_type === "college_student" || profile.user_type === "fresher") && (
                  <>
                    <FormSection label="Domain" labelSpaced>
                      <PillGroup>
                        {DOMAIN_OPTIONS.map((item) => (
                          <button key={item} type="button" className={pillButtonClass(profile.domain === item)} onClick={() => updateProfile("domain", item)}>
                            {item}
                          </button>
                        ))}
                      </PillGroup>
                    </FormSection>
                    <FormSection label="Course">
                      <input className="input-base" value={profile.course} onChange={(e) => updateProfile("course", e.target.value)} placeholder="B.Tech CSE / MBA / BBA ..." />
                    </FormSection>
                    <FormSection label="Passout Year" labelSpaced>
                      <PillGroup>
                        {DEFAULT_YEARS.map((year) => (
                          <button
                            key={year}
                            type="button"
                            className={pillButtonClass(profile.passout_year === year)}
                            onClick={() => updateProfile("passout_year", year)}
                          >
                            {year}
                          </button>
                        ))}
                      </PillGroup>
                    </FormSection>
                    <FormSection label="College Name">
                      <select
                        className="input-base"
                        value={selectedUniversity}
                        onChange={(e) => {
                          const selected = e.target.value;
                          setSelectedUniversity(selected);
                          if (selected === OTHER_UNIVERSITY_VALUE) {
                            if (UNIVERSITY_OPTION_VALUES.has(profile.college_name)) {
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
                      </select>
                    </FormSection>
                    {selectedUniversity === OTHER_UNIVERSITY_VALUE && (
                      <FormSection label="Enter University Name">
                        <input
                          className="input-base"
                          value={profile.college_name}
                          onChange={(e) => updateProfile("college_name", e.target.value)}
                          placeholder="Type your university name manually"
                        />
                      </FormSection>
                    )}
                    {selectedUniversity !== OTHER_UNIVERSITY_VALUE && profile.college_name.trim().length > 0 && !UNIVERSITY_OPTION_VALUES.has(profile.college_name) && (
                      <div className="vv-form-helper">
                        Existing university not in the current list. Choose &quot;{OTHER_INSTITUTION_LABEL}&quot; to edit manually.
                      </div>
                    )}
                  </>
                )}

                {profile.account_type === "candidate" && profile.user_type === "school_student" && (
                  <FormSection label="Class / Grade" labelSpaced>
                    <PillGroup>
                      {SCHOOL_GRADES.map((grade) => (
                        <button key={grade} type="button" className={pillButtonClass(profile.class_grade === grade)} onClick={() => updateProfile("class_grade", grade)}>
                          {grade}
                        </button>
                      ))}
                    </PillGroup>
                  </FormSection>
                )}
 
                {profile.account_type === "candidate" && profile.user_type === "professional" && (
                  <>
                    <FormSection label="Current Job Role">
                      <input className="input-base" value={profile.current_job_role} onChange={(e) => updateProfile("current_job_role", e.target.value)} placeholder="Software Engineer / Analyst ..." />
                    </FormSection>
                    <FormSection label="Total Work Experience">
                      <PillGroup>
                        {EXPERIENCE_OPTIONS.map((option) => (
                          <button key={option} type="button" className={pillButtonClass(profile.total_work_experience === option)} onClick={() => updateProfile("total_work_experience", option)}>
                            {option}
                          </button>
                        ))}
                      </PillGroup>
                    </FormSection>
                  </>
                )}

                {profile.account_type === "candidate" && resumeRequiredForUserType && (
                  <FormSection
                    label="Resume / CV (Required)"
                    className="onboarding-upload-card"
                    helper="Upload your resume so recommendations and shortlisting can be personalized from your profile + CV."
                  >
                    {profile.resume_filename ? (
                      <div className="onboarding-upload-status">
                        Uploaded: {profile.resume_filename}
                        {profile.resume_uploaded_at ? (
                          <span className="onboarding-upload-date">
                            {" "}
                            ({new Date(profile.resume_uploaded_at).toLocaleDateString()})
                          </span>
                        ) : null}
                      </div>
                    ) : (
                      <div className="onboarding-upload-status warning">
                        Resume not uploaded yet.
                      </div>
                    )}
                    <div className="onboarding-inline-actions">
                      <label className={`btn-secondary onboarding-upload-trigger ${resumeUploading ? "is-disabled" : ""}`}>
                        {resumeUploading ? "Uploading..." : profile.resume_filename ? "Replace Resume" : "Upload Resume"}
                        <input
                          type="file"
                          accept=".txt,.pdf,.doc,.docx"
                          disabled={resumeUploading}
                          className="vv-hidden-input"
                          onChange={(event) => {
                            const nextFile = event.target.files?.[0];
                            if (!nextFile) {
                              return;
                            }
                            void handleResumeUpload(nextFile);
                            event.currentTarget.value = "";
                          }}
                        />
                      </label>
                      {profile.resume_filename && (
                        <button type="button" className="btn-secondary" disabled={resumeUploading} onClick={() => void handleResumeDelete()}>
                          Remove Resume
                        </button>
                      )}
                    </div>
                  </FormSection>
                )}

                {profile.account_type === "employer" && (
                  <>
                    <FormSection label="Current Organisation">
                      <input
                        className="input-base"
                        value={profile.company_name}
                        onChange={(e) => {
                          updateProfile("company_name", e.target.value);
                          updateProfile("college_name", e.target.value);
                        }}
                        placeholder="Company name"
                        list="employer-org-suggestions"
                      />
                      <datalist id="employer-org-suggestions">
                        {EMPLOYER_ORGANIZATION_SUGGESTIONS.map((item) => (
                          <option key={item} value={item} />
                        ))}
                      </datalist>
                    </FormSection>

                    <FormSection label="Designation">
                      <select
                        className="input-base"
                        value={employerRoleSelection}
                        onChange={(e) => {
                          const value = e.target.value;
                          setEmployerRoleSelection(value);
                          if (value === "Other") {
                            updateProfile("current_job_role", "");
                          } else {
                            updateProfile("current_job_role", value);
                          }
                        }}
                      >
                        <option value="">Job Role</option>
                        {EMPLOYER_ROLE_OPTIONS.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </FormSection>

                    {employerRoleSelection === "Other" && (
                      <FormSection>
                        <input
                          className="input-base"
                          value={profile.current_job_role}
                          onChange={(e) => updateProfile("current_job_role", e.target.value)}
                          placeholder="If Other, enter custom designation"
                        />
                      </FormSection>
                    )}

                    <FormSection label="You&apos;re Hiring for" labelSpaced>
                      <PillGroup>
                        <button type="button" className={pillButtonClass(profile.hiring_for === "myself")} onClick={() => updateProfile("hiring_for", "myself")}>
                          Myself
                        </button>
                        <button type="button" className={pillButtonClass(profile.hiring_for === "others")} onClick={() => updateProfile("hiring_for", "others")}>
                          Others
                        </button>
                      </PillGroup>
                    </FormSection>

                    <FieldGrid variant="two">
                      <input
                        className="input-base"
                        value={profile.company_website}
                        onChange={(e) => updateProfile("company_website", e.target.value)}
                        placeholder="Company website (optional)"
                      />
                      <input
                        className="input-base"
                        value={profile.company_size}
                        onChange={(e) => updateProfile("company_size", e.target.value)}
                        placeholder="Company size (optional)"
                      />
                    </FieldGrid>
                  </>
                )}
              </>
            )}

            {step === 3 && profile.account_type === "candidate" && (
              <>
                <FormSection label="What brings you here?" labelSpaced>
                  <PillGroup>
                    {GOAL_OPTIONS.map((goal) => (
                      <button key={goal} type="button" className={pillButtonClass(profile.goals.includes(goal))} onClick={() => toggleGoal(goal)}>
                        {goal}
                      </button>
                    ))}
                  </PillGroup>
                </FormSection>
                <FormSection label="Interested Career Roles">
                  <input className="input-base" value={profile.preferred_roles} onChange={(e) => updateProfile("preferred_roles", e.target.value)} placeholder="Data Scientist, Backend Engineer, Analyst..." />
                </FormSection>
                <FormSection label="Preferred Work Location">
                  <input className="input-base" value={profile.preferred_locations} onChange={(e) => updateProfile("preferred_locations", e.target.value)} placeholder="Bangalore, Pune, Remote..." />
                </FormSection>
                <ToggleRow checked={profile.pan_india} onChange={(checked) => updateProfile("pan_india", checked)}>
                  Open to Pan India opportunities
                </ToggleRow>
                <ToggleRow checked={profile.prefer_wfh} onChange={(checked) => updateProfile("prefer_wfh", checked)}>
                  I prefer Work from Home (WFH)
                </ToggleRow>
              </>
            )}
          </div>

          <div className="onboarding-footer">
            <button
              type="button"
              className="btn-secondary"
              onClick={logout}
            >
              Logout
            </button>
            <div className="onboarding-footer-actions">
              {step > 1 && (
                <button type="button" className="btn-secondary" onClick={() => setStep((current) => Math.max(1, current - 1))}>
                  Back
                </button>
              )}
              {step < totalSteps ? (
                <button
                  type="button"
                  className="btn-primary"
                  disabled={saving || (step === 1 ? !canContinueStep1 : !canContinueStep2)}
                  onClick={() => void handleSave(false, totalSteps)}
                >
                  Continue
                </button>
              ) : (
                <button type="button" className="btn-primary" disabled={saving} onClick={() => void handleSave(true, totalSteps)}>
                  {saving ? "Finishing..." : "Finish"}
                </button>
              )}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
