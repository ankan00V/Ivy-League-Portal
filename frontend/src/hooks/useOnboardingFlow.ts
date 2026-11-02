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
  profileLoaded: boolean;
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
  retry: () => void;
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
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [employerRoleSelection, setEmployerRoleSelection] = useState<string>("");
  const [selectedUniversity, setSelectedUniversity] = useState<string>("");
  const [status, setStatus] = useState<TStatus | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login?next=/onboarding");
      return;
    }

    const run = async () => {
      try {
        setLoading(true);
        setProfileLoaded(false);
        setError(null);
        const [profileRes, statusRes] = await Promise.all([
          fetch(apiUrl("/api/v1/users/me/profile"), createAuthenticatedFetchInit({}, token)),
          fetch(apiUrl("/api/v1/users/me/onboarding-status"), createAuthenticatedFetchInit({}, token)),
        ]);
        if (profileRes.status === 401 || statusRes.status === 401) {
          clearAccessToken("expired");
          router.replace("/login?next=/onboarding");
          return;
        }
        if (!profileRes.ok || !statusRes.ok) {
          throw new Error("We could not load your saved onboarding details. Your progress is safe—please retry.");
        }

        const profilePayload = (await profileRes.json()) as Record<string, unknown>;
        const onboardingStatus = (await statusRes.json()) as TStatus;
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
        setProfileLoaded(true);
      } catch (err) {
        setProfileLoaded(false);
        setError(getUnknownErrorMessage(err, "We could not load onboarding. Your progress is safe—please retry."));
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
    reloadKey,
  ]);

  const retry = useCallback(() => {
    setError(null);
    setReloadKey((current) => current + 1);
  }, []);

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
    profileLoaded,
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
    retry,
    logout,
  };
}
