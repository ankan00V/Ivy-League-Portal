"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { apiUrl } from "@/lib/api";
import { clearAccessToken, createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";
import { fetchWithTimeout } from "@/lib/auth-network";

type UseOnboardingFlowArgs<TProfile, TPayload> = {
  profile: TProfile;
  setProfile: Dispatch<SetStateAction<TProfile>>;
  hydrateProfilePayload: (payload: Record<string, unknown>, previous: TProfile) => TProfile;
  hydrateResumePayload: (payload: Record<string, unknown>, previous: TProfile) => TProfile;
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
  hydrateResumePayload,
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
  const profileRef = useRef(profile);
  const saveInProgress = useRef(false);
  const uploadInProgress = useRef(false);
  useEffect(() => { profileRef.current = profile; }, [profile]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
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
          fetchWithTimeout(apiUrl("/api/v1/users/me/profile"), createAuthenticatedFetchInit({ signal: controller.signal }, token)),
          fetchWithTimeout(apiUrl("/api/v1/users/me/onboarding-status"), createAuthenticatedFetchInit({ signal: controller.signal }, token)),
        ]);
        if (!active) return;
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
        if (!active) return;
        if (onboardingStatus?.completed) {
          const accountType = String(profilePayload.account_type || "candidate").toLowerCase();
          router.replace(resolveRouteForAccountType(accountType));
          return;
        }

        setStatus(onboardingStatus);
        const next = hydrateProfilePayload(profilePayload, profileRef.current);
        setProfile(next);
        setSelectedUniversity(deriveUniversitySelection(getCollegeNameFromProfile(next)));
        const existingRole = String(getCurrentRoleFromProfile(next) || "").trim();
        setEmployerRoleSelection(!existingRole ? "" : employerRoleOptions.includes(existingRole) ? existingRole : "Other");
        // The API returns missing field names, not numeric page indexes. Resume
        // at identity only when identity is incomplete, otherwise show details.
        const identityFields = new Set(["first_name", "mobile", "account_type", "user_type", "consent_data_processing"]);
        const missing = onboardingStatus.missing_fields || [];
        setStep(missing.length && !missing.some((field) => identityFields.has(field)) ? 2 : 1);
        setProfileLoaded(true);
      } catch (err) {
        if (!active) return;
        setProfileLoaded(false);
        setError(getUnknownErrorMessage(err, "We could not load onboarding. Your progress is safe—please retry."));
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => { active = false; controller.abort(); };
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
    if (uploadInProgress.current || saveInProgress.current) return;
    if (!/\.(pdf|docx?|txt)$/i.test(file.name) || file.size === 0 || file.size > 8 * 1024 * 1024) {
      setError("Choose a non-empty PDF, DOCX, DOC, or TXT resume up to 8 MB.");
      return;
    }
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    uploadInProgress.current = true;
    setResumeUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetchWithTimeout(
        apiUrl("/api/v1/users/me/resume"),
        createAuthenticatedFetchInit(
          {
            method: "POST",
            body: form,
          },
          token,
        ),
        60_000,
      );
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to upload resume"));
      }
      setProfile((prev) => hydrateResumePayload(payload, prev));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to upload resume"));
    } finally {
      uploadInProgress.current = false;
      setResumeUploading(false);
    }
  }, [router, setProfile, hydrateResumePayload]);

  const handleResumeDelete = useCallback(async () => {
    if (uploadInProgress.current || saveInProgress.current) return;
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    uploadInProgress.current = true;
    setResumeUploading(true);
    setError(null);
    try {
      const res = await fetchWithTimeout(
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
      setProfile((prev) => hydrateResumePayload(payload, prev));
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to remove resume"));
    } finally {
      uploadInProgress.current = false;
      setResumeUploading(false);
    }
  }, [router, setProfile, hydrateResumePayload]);

  const handleSave = useCallback(async (finish: boolean, totalSteps: number) => {
    if (saveInProgress.current || uploadInProgress.current) return;
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    saveInProgress.current = true;
    setSaving(true);
    setError(null);
    try {
      const payloadToSave = buildOnboardingPayload(profile);
      const res = await fetchWithTimeout(
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
      if (res.status === 401) {
        clearAccessToken("expired");
        router.replace("/login?next=/onboarding");
        return;
      }
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to save onboarding"));
      }

      const statusRes = await fetchWithTimeout(
        apiUrl("/api/v1/users/me/onboarding-status"),
        createAuthenticatedFetchInit({}, token),
      );
      if (!statusRes.ok) {
        throw new Error("Your details were saved, but we could not confirm the next step. Please retry to continue.");
      }
      const onboardingStatus = (await statusRes.json()) as TStatus;
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
      saveInProgress.current = false;
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
