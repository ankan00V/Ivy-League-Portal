"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import BrandLogo from "@/components/BrandLogo";
import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

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
  bio: string;
  skills: string;
  interests: string;
  achievements: string;
  education: string;
  resume_url: string;
  resume_filename: string;
  resume_uploaded_at: string;
};

type UserPayload = {
  email: string;
};

function toText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function toNullableNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export default function ProfilePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingResume, setUploadingResume] = useState(false);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    bio: "",
    skills: "",
    interests: "",
    achievements: "",
    education: "",
    resume_url: "",
    resume_filename: "",
    resume_uploaded_at: "",
  });

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

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const run = async () => {
      try {
        const [userRes, profileRes] = await Promise.all([
          fetch(apiUrl("/api/v1/users/me"), { headers: { Authorization: `Bearer ${token}` } }),
          fetch(apiUrl("/api/v1/users/me/profile"), { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        const userPayload = (await userRes.json().catch(() => ({}))) as UserPayload;
        const profilePayload = (await profileRes.json().catch(() => ({}))) as Record<string, unknown>;

        if (!userRes.ok || !profileRes.ok) {
          throw new Error(getApiErrorMessage(profilePayload, "Unable to load profile"));
        }

        setEmail(toText(userPayload.email));
        setProfile({
          account_type: (toText(profilePayload.account_type) || "candidate") as AccountType,
          first_name: toText(profilePayload.first_name),
          last_name: toText(profilePayload.last_name),
          mobile: toText(profilePayload.mobile),
          country_code: toText(profilePayload.country_code) || "+91",
          user_type: (toText(profilePayload.user_type) || "") as UserType | "",
          domain: toText(profilePayload.domain),
          course: toText(profilePayload.course),
          passout_year: toNullableNumber(profilePayload.passout_year),
          class_grade: toNullableNumber(profilePayload.class_grade),
          current_job_role: toText(profilePayload.current_job_role),
          total_work_experience: toText(profilePayload.total_work_experience),
          college_name: toText(profilePayload.college_name),
          company_name: toText(profilePayload.company_name),
          company_website: toText(profilePayload.company_website),
          company_size: toText(profilePayload.company_size),
          company_description: toText(profilePayload.company_description),
          hiring_for: (toText(profilePayload.hiring_for) || "") as "myself" | "others" | "",
          goals: Array.isArray(profilePayload.goals) ? profilePayload.goals.map((item) => String(item)) : [],
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
          resume_url: toText(profilePayload.resume_url),
          resume_filename: toText(profilePayload.resume_filename),
          resume_uploaded_at: toText(profilePayload.resume_uploaded_at),
        });
      } catch (err) {
        setError(getUnknownErrorMessage(err, "Unable to load profile"));
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [router]);

  const updateProfile = <K extends keyof ProfilePayload>(field: K, value: ProfilePayload[K]) => {
    setProfile((prev) => ({ ...prev, [field]: value }));
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
      const res = await fetch(apiUrl("/api/v1/users/me/profile"), {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(profile),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update profile"));
      }
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
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to upload resume"));
      }
      setProfile((prev) => ({
        ...prev,
        skills: typeof payload.skills === "string" ? payload.skills : prev.skills,
        resume_url: typeof payload.resume_url === "string" ? payload.resume_url : prev.resume_url,
        resume_filename: typeof payload.resume_filename === "string" ? payload.resume_filename : file.name,
        resume_uploaded_at: typeof payload.resume_uploaded_at === "string" ? payload.resume_uploaded_at : prev.resume_uploaded_at,
      }));
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
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to remove resume"));
      }
      setProfile((prev) => ({
        ...prev,
        resume_url: "",
        resume_filename: "",
        resume_uploaded_at: "",
      }));
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

  if (loading) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg-base)" }}>
        <p style={{ color: "var(--text-secondary)", fontWeight: 700 }}>Loading profile...</p>
      </main>
    );
  }

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg-base)", padding: "1.25rem" }}>
      <section className="card-panel" style={{ maxWidth: "980px", margin: "0 auto", display: "grid", gap: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <BrandLogo size="sm" />
            <h1 style={{ fontSize: "2rem", margin: 0 }}>View Profile</h1>
          </div>
          <Link href={profile.account_type === "employer" ? "/employer/dashboard" : "/dashboard"} className="btn-secondary">
            Back to Dashboard
          </Link>
        </div>

        {error && (
          <div style={{ background: "rgba(239,68,68,0.08)", border: "2px solid #ef4444", color: "#b91c1c", borderRadius: "var(--radius-sm)", padding: "0.75rem" }}>
            {error}
          </div>
        )}
        {message && (
          <div style={{ background: "rgba(34,197,94,0.08)", border: "2px solid #16a34a", color: "#166534", borderRadius: "var(--radius-sm)", padding: "0.75rem" }}>
            {message}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <div>
            <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Email (Read-only)</label>
            <input className="input-base" value={email} disabled />
          </div>
          <div>
            <label style={{ fontWeight: 700, display: "block", marginBottom: "0.35rem" }}>Account Type</label>
            <input className="input-base" value={profile.account_type} disabled />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <input className="input-base" placeholder="First name" value={profile.first_name} onChange={(event) => updateProfile("first_name", event.target.value)} />
          <input className="input-base" placeholder="Last name" value={profile.last_name} onChange={(event) => updateProfile("last_name", event.target.value)} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: "0.75rem" }}>
          <input className="input-base" placeholder="Country code" value={profile.country_code} onChange={(event) => updateProfile("country_code", event.target.value)} />
          <input className="input-base" placeholder="Mobile" value={profile.mobile} onChange={(event) => updateProfile("mobile", event.target.value)} />
        </div>

        {profile.account_type === "candidate" ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <select className="input-base" value={profile.user_type} onChange={(event) => updateProfile("user_type", event.target.value as UserType)}>
                <option value="">Select user type</option>
                <option value="school_student">School Student</option>
                <option value="college_student">College Student</option>
                <option value="fresher">Fresher</option>
                <option value="professional">Educator / Professional</option>
              </select>
              <input className="input-base" placeholder="Domain" value={profile.domain} onChange={(event) => updateProfile("domain", event.target.value)} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Course" value={profile.course} onChange={(event) => updateProfile("course", event.target.value)} />
              <input
                className="input-base"
                placeholder="Passout year"
                type="number"
                value={profile.passout_year ?? ""}
                onChange={(event) => updateProfile("passout_year", event.target.value ? Number(event.target.value) : null)}
              />
              <input
                className="input-base"
                placeholder="Class / Grade"
                type="number"
                value={profile.class_grade ?? ""}
                onChange={(event) => updateProfile("class_grade", event.target.value ? Number(event.target.value) : null)}
              />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Current Job Role" value={profile.current_job_role} onChange={(event) => updateProfile("current_job_role", event.target.value)} />
              <input className="input-base" placeholder="Total Work Experience" value={profile.total_work_experience} onChange={(event) => updateProfile("total_work_experience", event.target.value)} />
            </div>
            <input className="input-base" placeholder="College / Institution Name" value={profile.college_name} onChange={(event) => updateProfile("college_name", event.target.value)} />
            <textarea className="input-base" rows={3} placeholder="Bio" value={profile.bio} onChange={(event) => updateProfile("bio", event.target.value)} />
            <textarea className="input-base" rows={2} placeholder="Skills (comma separated)" value={profile.skills} onChange={(event) => updateProfile("skills", event.target.value)} />
            <textarea className="input-base" rows={2} placeholder="Interests (comma separated)" value={profile.interests} onChange={(event) => updateProfile("interests", event.target.value)} />
            <textarea className="input-base" rows={2} placeholder="Education details" value={profile.education} onChange={(event) => updateProfile("education", event.target.value)} />
            <textarea className="input-base" rows={2} placeholder="Achievements" value={profile.achievements} onChange={(event) => updateProfile("achievements", event.target.value)} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Preferred roles" value={profile.preferred_roles} onChange={(event) => updateProfile("preferred_roles", event.target.value)} />
              <input className="input-base" placeholder="Preferred locations" value={profile.preferred_locations} onChange={(event) => updateProfile("preferred_locations", event.target.value)} />
            </div>
          </>
        ) : (
          <>
            <input className="input-base" placeholder="Company Name" value={profile.company_name} onChange={(event) => updateProfile("company_name", event.target.value)} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Current Job Role" value={profile.current_job_role} onChange={(event) => updateProfile("current_job_role", event.target.value)} />
              <select className="input-base" value={profile.hiring_for} onChange={(event) => updateProfile("hiring_for", event.target.value as "myself" | "others" | "")}>
                <option value="">Hiring for</option>
                <option value="myself">Myself</option>
                <option value="others">Others</option>
              </select>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <input className="input-base" placeholder="Company Website" value={profile.company_website} onChange={(event) => updateProfile("company_website", event.target.value)} />
              <input className="input-base" placeholder="Company Size" value={profile.company_size} onChange={(event) => updateProfile("company_size", event.target.value)} />
            </div>
            <textarea className="input-base" rows={4} placeholder="Company Description" value={profile.company_description} onChange={(event) => updateProfile("company_description", event.target.value)} />
          </>
        )}

        <section style={{ border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "0.9rem", background: "var(--bg-surface)" }}>
          <h2 style={{ margin: "0 0 0.6rem", fontSize: "1.15rem" }}>Resume</h2>
          {profile.resume_filename ? (
            <p style={{ fontWeight: 700, marginBottom: "0.35rem" }}>
              {profile.resume_filename}
              {resumeUploadedOn ? <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}> · Uploaded {resumeUploadedOn}</span> : null}
            </p>
          ) : (
            <p style={{ fontWeight: 700, color: "#b91c1c", marginBottom: "0.35rem" }}>No resume uploaded yet.</p>
          )}
          <p style={{ color: "var(--text-secondary)", fontWeight: 600, marginBottom: "0.6rem" }}>
            Supported formats: .txt, .pdf, .doc, .docx. Resume signals are used for personalization.
          </p>
          <div style={{ display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
            <label className="btn-secondary" style={{ cursor: uploadingResume ? "not-allowed" : "pointer", opacity: uploadingResume ? 0.7 : 1 }}>
              {uploadingResume ? "Uploading..." : profile.resume_filename ? "Replace Resume" : "Upload Resume"}
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
            {profile.resume_filename && (
              <>
                <button type="button" className="btn-secondary" onClick={() => void downloadResume()}>
                  View / Download Resume
                </button>
                <button type="button" className="btn-secondary" onClick={() => void deleteResume()} disabled={uploadingResume}>
                  Remove Resume
                </button>
              </>
            )}
          </div>
        </section>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button type="button" className="btn-primary" disabled={saving} onClick={() => void saveProfile()}>
            {saving ? "Saving..." : "Save Profile"}
          </button>
        </div>
      </section>
    </main>
  );
}
