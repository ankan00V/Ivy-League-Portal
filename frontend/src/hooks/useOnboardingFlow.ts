"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { apiUrl } from "@/lib/api";
import { clearAccessToken, createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type UseOnboardingFlowArgs<TProfile, TPayload> = {
  profile: TProfile;
  setProfile: Dispatch<SetStateAction<TProfile>>;
  hydrateProfilePayload: (payload: Record<string, unknown>, previous: TProfile) => TProfile;
  buildOnboardingPayload: (profile: TProfile) => TPayload;
  deriveUniversitySelection: (value: string) => string;
  employerRoleOptions: string[];
  getAccountTypeFromProfile: (profile: TProfile) => string;
  getCollegeNameFromProfile: (profile: TProfile) => string;
  getCurrentRoleFromProfile: (profile: TProfile) => string;
  resolveRouteForAccountType: (accountType: string) => string;
};

type UseOnboardingFlowResult<TStatus> = {
  loading: boolean;
  saving: boolean;
  step: number;
  setStep: Dispatch<SetStateAction<number>>;
  error: string | null;
  setError: Dispatch<SetStateAction<string | null>>;
  resumeUploading: boolean;
  employerRoleSelection: string;
  setEmployerRoleSelection: Dispatch<SetStateAction<string>>;
  selectedUniversity: string;
  setSelectedUniversity: Dispatch<SetStateAction<string>>;
  status: TStatus | null;
  handleResumeUpload: (file: File) => Promise<void>;
  handleResumeDelete: () => Promise<void>;
  handleSave: (finish: boolean, totalSteps: number) => Promise<void>;
  logout: () => void;
};

export function useOnboardingFlow<TProfile, TPayload, TStatus extends { completed?: boolean; missing_fields?: string[] }>({
  profile,
  setProfile,
  hydrateProfilePayload,
  buildOnboardingPayload,
  deriveUniversitySelection,
  employerRoleOptions,
  getAccountTypeFromProfile,
  getCollegeNameFromProfile,
  getCurrentRoleFromProfile,
  resolveRouteForAccountType,
}: UseOnboardingFlowArgs<TProfile, TPayload>): UseOnboardingFlowResult<TStatus> {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [employerRoleSelection, setEmployerRoleSelection] = useState<string>("");
  const [selectedUniversity, setSelectedUniversity] = useState<string>("");
  const [status, setStatus] = useState<TStatus | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    const run = async () => {
      try {
        const [profileRes, statusRes] = await Promise.all([
          fetch(apiUrl("/api/v1/users/me/profile"), createAuthenticatedFetchInit({}, token)),
          fetch(apiUrl("/api/v1/users/me/onboarding-status"), createAuthenticatedFetchInit({}, token)),
        ]);
        if (!profileRes.ok) {
          throw new Error("Failed to load profile");
        }

        const profilePayload = (await profileRes.json()) as Record<string, unknown>;
        const onboardingStatus = statusRes.ok ? ((await statusRes.json()) as TStatus) : null;
        if (onboardingStatus?.completed) {
          const accountType = String(profilePayload.account_type || "candidate").toLowerCase();
          router.replace(resolveRouteForAccountType(accountType));
          return;
        }

        setStatus(onboardingStatus);
        setProfile((prev) => {
          const next = hydrateProfilePayload(profilePayload, prev);
          setSelectedUniversity(deriveUniversitySelection(getCollegeNameFromProfile(next)));

          const existingRole = String(getCurrentRoleFromProfile(next) || "").trim();
          if (existingRole.length === 0) {
            setEmployerRoleSelection("");
          } else if (employerRoleOptions.includes(existingRole)) {
            setEmployerRoleSelection(existingRole);
          } else {
            setEmployerRoleSelection("Other");
          }
          return next;
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load onboarding");
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [
    router,
    setProfile,
    hydrateProfilePayload,
    deriveUniversitySelection,
    employerRoleOptions,
    getCollegeNameFromProfile,
    getCurrentRoleFromProfile,
    resolveRouteForAccountType,
  ]);

  const handleResumeUpload = useCallback(async (file: File) => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setResumeUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        apiUrl("/api/v1/users/me/resume"),
        createAuthenticatedFetchInit(
          {
            method: "POST",
            body: form,
          },
          token,
        ),
      );
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to upload resume"));
      }
      setProfile((prev) => hydrateProfilePayload(payload, prev));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to upload resume"));
    } finally {
      setResumeUploading(false);
    }
  }, [router, setProfile, hydrateProfilePayload]);

  const handleResumeDelete = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setResumeUploading(true);
    setError(null);
    try {
      const res = await fetch(
        apiUrl("/api/v1/users/me/resume"),
        createAuthenticatedFetchInit(
          {
            method: "DELETE",
          },
          token,
        ),
      );
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to remove resume"));
      }
      setProfile((prev) => hydrateProfilePayload(payload, prev));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to remove resume"));
    } finally {
      setResumeUploading(false);
    }
  }, [router, setProfile, hydrateProfilePayload]);

  const handleSave = useCallback(async (finish: boolean, totalSteps: number) => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payloadToSave = buildOnboardingPayload(profile);
      const res = await fetch(
        apiUrl("/api/v1/users/me/onboarding"),
        createAuthenticatedFetchInit(
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(payloadToSave),
          },
          token,
        ),
      );
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to save onboarding"));
      }

      const statusRes = await fetch(
        apiUrl("/api/v1/users/me/onboarding-status"),
        createAuthenticatedFetchInit({}, token),
      );
      const onboardingStatus = statusRes.ok ? ((await statusRes.json()) as TStatus) : null;
      setStatus(onboardingStatus);

      if (finish && onboardingStatus?.completed) {
        router.push(resolveRouteForAccountType(getAccountTypeFromProfile(profile)));
      } else if (finish) {
        const missing = onboardingStatus?.missing_fields?.join(", ") || "some required fields";
        setError(`Please complete: ${missing}`);
      } else {
        setStep((current) => Math.min(totalSteps, current + 1));
      }
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to save onboarding"));
    } finally {
      setSaving(false);
    }
  }, [router, profile, buildOnboardingPayload, getAccountTypeFromProfile, resolveRouteForAccountType]);

  const logout = useCallback(() => {
    clearAccessToken();
    router.replace("/login");
  }, [router]);

  return {
    loading,
    saving,
    step,
    setStep,
    error,
    setError,
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
  };
}
