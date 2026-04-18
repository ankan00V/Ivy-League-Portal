"use client";

import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth-session";

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
};

type OnboardingStatus = {
  completed: boolean;
  progress_percent: number;
  missing_fields: string[];
  recommended_next_step: string;
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

const ONBOARDING_VISUALS = [
  "https://images.unsplash.com/photo-1529074963764-98f45c47344b?auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=1200&q=80",
];

function pillButtonStyle(active: boolean): React.CSSProperties {
  return {
    border: active ? "2px solid var(--brand-primary)" : "2px dashed var(--border-subtle)",
    background: active ? "rgba(59,130,246,0.08)" : "var(--bg-surface)",
    color: "var(--text-primary)",
    borderRadius: "999px",
    padding: "0.55rem 0.9rem",
    cursor: "pointer",
    fontWeight: 700,
    minWidth: "fit-content",
  };
}

export default function OnboardingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [employerRoleSelection, setEmployerRoleSelection] = useState<string>("");
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
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
  });

  const totalSteps = profile.account_type === "employer" ? 2 : 3;
  const visual = useMemo(() => ONBOARDING_VISUALS[(step - 1) % ONBOARDING_VISUALS.length], [step]);

  useEffect(() => {
    if (step > totalSteps) {
      setStep(totalSteps);
    }
  }, [step, totalSteps]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    const run = async () => {
      try {
        const [profileRes, statusRes] = await Promise.all([
          fetch(apiUrl("/api/v1/users/me/profile"), {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(apiUrl("/api/v1/users/me/onboarding-status"), {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);
        if (!profileRes.ok) {
          throw new Error("Failed to load profile");
        }
        const profilePayload = await profileRes.json();
        const onboardingStatus = statusRes.ok ? ((await statusRes.json()) as OnboardingStatus) : null;
        if (onboardingStatus?.completed) {
          const accountType = String(profilePayload.account_type || "candidate").toLowerCase();
          router.replace(accountType === "employer" ? "/employer/dashboard" : "/dashboard");
          return;
        }
        const asText = (value: unknown): string => (typeof value === "string" ? value : "");
        const asBool = (value: unknown): boolean => Boolean(value);
        const asNullableNumber = (value: unknown): number | null => (typeof value === "number" ? value : null);

        setStatus(onboardingStatus);
        setProfile((prev) => ({
          ...prev,
          account_type: (profilePayload.account_type || "candidate") as AccountType,
          first_name: asText(profilePayload.first_name),
          last_name: asText(profilePayload.last_name),
          mobile: asText(profilePayload.mobile),
          country_code: asText(profilePayload.country_code) || "+91",
          user_type: (profilePayload.user_type || "") as UserType | "",
          domain: asText(profilePayload.domain),
          course: asText(profilePayload.course),
          passout_year: asNullableNumber(profilePayload.passout_year),
          class_grade: asNullableNumber(profilePayload.class_grade),
          current_job_role: asText(profilePayload.current_job_role),
          total_work_experience: asText(profilePayload.total_work_experience),
          college_name: asText(profilePayload.college_name),
          company_name: asText(profilePayload.company_name),
          company_website: asText(profilePayload.company_website),
          company_size: asText(profilePayload.company_size),
          company_description: asText(profilePayload.company_description),
          hiring_for: (profilePayload.hiring_for || "") as "myself" | "others" | "",
          goals: Array.isArray(profilePayload.goals) ? profilePayload.goals.map((item: unknown) => String(item)) : [],
          preferred_roles: asText(profilePayload.preferred_roles),
          preferred_locations: asText(profilePayload.preferred_locations),
          pan_india: asBool(profilePayload.pan_india),
          prefer_wfh: asBool(profilePayload.prefer_wfh),
          consent_data_processing: asBool(profilePayload.consent_data_processing),
          consent_updates: asBool(profilePayload.consent_updates),
        }));
        const existingRole = String(profilePayload.current_job_role || "").trim();
        if (existingRole.length === 0) {
          setEmployerRoleSelection("");
        } else if (EMPLOYER_ROLE_OPTIONS.includes(existingRole)) {
          setEmployerRoleSelection(existingRole);
        } else {
          setEmployerRoleSelection("Other");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load onboarding");
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [router]);

  const missingConsent = !profile.consent_data_processing;
  const requiresUserType = profile.account_type === "candidate";
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
        profile.college_name.trim().length > 0
      );
    }
    if (profile.user_type === "professional") {
      return profile.current_job_role.trim().length > 0 && profile.total_work_experience.trim().length > 0;
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

  const handleSave = async (finish: boolean) => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/v1/users/me/onboarding"), {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(profile),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload.detail || "Unable to save onboarding");
      }

      const statusRes = await fetch(apiUrl("/api/v1/users/me/onboarding-status"), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const onboardingStatus = statusRes.ok ? ((await statusRes.json()) as OnboardingStatus) : null;
      setStatus(onboardingStatus);

      if (finish && onboardingStatus?.completed) {
        router.push(profile.account_type === "employer" ? "/employer/dashboard" : "/dashboard");
      } else if (finish) {
        const missing = onboardingStatus?.missing_fields?.join(", ") || "some required fields";
        setError(`Please complete: ${missing}`);
      } else {
        setStep((current) => Math.min(totalSteps, current + 1));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save onboarding");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg-base)" }}>
        <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>Preparing your onboarding experience...</p>
      </main>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background:
          "radial-gradient(circle at 10% 20%, rgba(251,191,36,0.08), transparent 30%), radial-gradient(circle at 85% 15%, rgba(59,130,246,0.07), transparent 26%), var(--bg-base)",
        padding: "1.5rem",
      }}
    >
      <section
        className="card-panel auth-shell"
        style={{
          width: "min(1120px, 100%)",
          minHeight: "760px",
          padding: 0,
          overflow: "hidden",
        }}
      >
        <aside
          className="auth-left-pane"
          style={{
            background: "#f7c948",
            padding: "1.25rem",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            borderRight: "2px solid var(--border-subtle)",
          }}
        >
          <BrandLogo size="md" />
          <div style={{ borderRadius: "var(--radius-md)", overflow: "hidden", border: "2px solid rgba(0,0,0,0.12)", background: "#fff" }}>
            <img src={visual} alt="Onboarding visual" style={{ width: "100%", height: "420px", objectFit: "cover", display: "block" }} />
          </div>
          <div>
            <h2 style={{ fontSize: "1.95rem", marginBottom: "0.45rem", color: "#111" }}>Set up your profile</h2>
            <p style={{ color: "rgba(0,0,0,0.78)", fontWeight: 600 }}>
              We personalize recommendations and matching based on this setup.
            </p>
          </div>
        </aside>

        <div className="auth-right-pane" style={{ padding: "1.75rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div>
            <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>You&apos;re almost there</h1>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              {Array.from({ length: totalSteps }, (_, idx) => idx + 1).map((n) => (
                <div
                  key={n}
                  style={{
                    height: "6px",
                    borderRadius: "999px",
                    width: "68px",
                    background: n <= step ? "var(--brand-primary)" : "var(--border-subtle)",
                  }}
                />
              ))}
              <span style={{ marginLeft: "0.5rem", color: "var(--text-secondary)", fontWeight: 700 }}>
                {status?.progress_percent ?? 0}% complete
              </span>
            </div>
          </div>

          {error && (
            <div style={{ background: "rgba(239,68,68,0.08)", border: "2px solid #ef4444", color: "#b91c1c", borderRadius: "var(--radius-sm)", padding: "0.75rem" }}>
              {error}
            </div>
          )}

          <div style={{ flex: 1, overflowY: "auto", display: "grid", gap: "1rem", paddingRight: "0.5rem" }}>
            {step === 1 && (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>First Name</label>
                    <input className="input-base" value={profile.first_name} onChange={(e) => updateProfile("first_name", e.target.value)} />
                  </div>
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Last Name</label>
                    <input className="input-base" value={profile.last_name} onChange={(e) => updateProfile("last_name", e.target.value)} />
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: "0.75rem" }}>
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Country Code</label>
                    <input className="input-base" value={profile.country_code} onChange={(e) => updateProfile("country_code", e.target.value)} />
                  </div>
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Mobile</label>
                    <input className="input-base" value={profile.mobile} onChange={(e) => updateProfile("mobile", e.target.value)} placeholder="1234567890" />
                  </div>
                </div>

                <div>
                  <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>Account Type</label>
                  <div style={{ display: "inline-flex", padding: "0.45rem 0.8rem", borderRadius: "999px", border: "2px solid var(--border-subtle)", background: "var(--bg-surface)" }}>
                    <strong>{profile.account_type === "employer" ? "Employer" : "Candidate"}</strong>
                  </div>
                  {profile.account_type === "employer" && (
                    <p style={{ marginTop: "0.45rem", color: "var(--text-secondary)", fontWeight: 600 }}>
                      Employer access is restricted to corporate email domains.
                    </p>
                  )}
                </div>

                {profile.account_type === "candidate" && (
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>User Type</label>
                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                      {[
                        { key: "school_student", label: "School Student" },
                        { key: "college_student", label: "College Student" },
                        { key: "fresher", label: "Fresher" },
                        { key: "professional", label: "Professional" },
                      ].map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          style={pillButtonStyle(profile.user_type === item.key)}
                          onClick={() => updateProfile("user_type", item.key as UserType)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={profile.consent_data_processing}
                    onChange={(event) => updateProfile("consent_data_processing", event.target.checked)}
                    style={{ marginTop: "0.2rem" }}
                  />
                  I agree to data processing and privacy policy.
                </label>
                <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={profile.consent_updates}
                    onChange={(event) => updateProfile("consent_updates", event.target.checked)}
                    style={{ marginTop: "0.2rem" }}
                  />
                  Keep me updated with relevant opportunities.
                </label>
              </>
            )}

            {step === 2 && (
              <>
                {profile.account_type === "candidate" && (profile.user_type === "college_student" || profile.user_type === "fresher") && (
                  <>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>Domain</label>
                      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                        {DOMAIN_OPTIONS.map((item) => (
                          <button key={item} type="button" style={pillButtonStyle(profile.domain === item)} onClick={() => updateProfile("domain", item)}>
                            {item}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Course</label>
                      <input className="input-base" value={profile.course} onChange={(e) => updateProfile("course", e.target.value)} placeholder="B.Tech CSE / MBA / BBA ..." />
                    </div>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>Passout Year</label>
                      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                        {DEFAULT_YEARS.map((year) => (
                          <button
                            key={year}
                            type="button"
                            style={pillButtonStyle(profile.passout_year === year)}
                            onClick={() => updateProfile("passout_year", year)}
                          >
                            {year}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>College Name</label>
                      <input className="input-base" value={profile.college_name} onChange={(e) => updateProfile("college_name", e.target.value)} placeholder="Your college / university" />
                    </div>
                  </>
                )}

                {profile.account_type === "candidate" && profile.user_type === "school_student" && (
                  <div>
                    <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>Class / Grade</label>
                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                      {SCHOOL_GRADES.map((grade) => (
                        <button key={grade} type="button" style={pillButtonStyle(profile.class_grade === grade)} onClick={() => updateProfile("class_grade", grade)}>
                          {grade}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {profile.account_type === "candidate" && profile.user_type === "professional" && (
                  <>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Current Job Role</label>
                      <input className="input-base" value={profile.current_job_role} onChange={(e) => updateProfile("current_job_role", e.target.value)} placeholder="Software Engineer / Analyst ..." />
                    </div>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Total Work Experience</label>
                      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                        {EXPERIENCE_OPTIONS.map((option) => (
                          <button key={option} type="button" style={pillButtonStyle(profile.total_work_experience === option)} onClick={() => updateProfile("total_work_experience", option)}>
                            {option}
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}

                {profile.account_type === "employer" && (
                  <>
                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Current Organisation</label>
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
                    </div>

                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Designation</label>
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
                    </div>

                    {employerRoleSelection === "Other" && (
                      <input
                        className="input-base"
                        value={profile.current_job_role}
                        onChange={(e) => updateProfile("current_job_role", e.target.value)}
                        placeholder="If Other, enter custom designation"
                      />
                    )}

                    <div>
                      <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>You&apos;re Hiring for</label>
                      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                        <button type="button" style={pillButtonStyle(profile.hiring_for === "myself")} onClick={() => updateProfile("hiring_for", "myself")}>
                          Myself
                        </button>
                        <button type="button" style={pillButtonStyle(profile.hiring_for === "others")} onClick={() => updateProfile("hiring_for", "others")}>
                          Others
                        </button>
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
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
                    </div>
                  </>
                )}
              </>
            )}

            {step === 3 && profile.account_type === "candidate" && (
              <>
                <div>
                  <label style={{ fontWeight: 700, display: "block", marginBottom: "0.5rem" }}>What brings you here?</label>
                  <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                    {GOAL_OPTIONS.map((goal) => (
                      <button key={goal} type="button" style={pillButtonStyle(profile.goals.includes(goal))} onClick={() => toggleGoal(goal)}>
                        {goal}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Interested Career Roles</label>
                  <input className="input-base" value={profile.preferred_roles} onChange={(e) => updateProfile("preferred_roles", e.target.value)} placeholder="Data Scientist, Backend Engineer, Analyst..." />
                </div>
                <div>
                  <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Preferred Work Location</label>
                  <input className="input-base" value={profile.preferred_locations} onChange={(e) => updateProfile("preferred_locations", e.target.value)} placeholder="Bangalore, Pune, Remote..." />
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
                  <input type="checkbox" checked={profile.pan_india} onChange={(e) => updateProfile("pan_india", e.target.checked)} />
                  Open to Pan India opportunities
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
                  <input type="checkbox" checked={profile.prefer_wfh} onChange={(e) => updateProfile("prefer_wfh", e.target.checked)} />
                  I prefer Work from Home (WFH)
                </label>
              </>
            )}
          </div>

          <div style={{ borderTop: "2px solid var(--border-subtle)", paddingTop: "1rem", display: "flex", justifyContent: "space-between", gap: "0.8rem" }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                clearAccessToken();
                router.replace("/login");
              }}
            >
              Logout
            </button>
            <div style={{ display: "flex", gap: "0.6rem" }}>
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
                  onClick={() => void handleSave(false)}
                >
                  Continue
                </button>
              ) : (
                <button type="button" className="btn-primary" disabled={saving} onClick={() => void handleSave(true)}>
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
