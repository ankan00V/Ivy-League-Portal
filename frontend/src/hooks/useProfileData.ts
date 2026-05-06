"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type UseProfileDataArgs<TProfile, TUpdatePayload> = {
  profile: TProfile;
  setProfile: Dispatch<SetStateAction<TProfile>>;
  hydrateProfilePayload: (payload: Record<string, unknown>) => TProfile;
  buildProfileUpdatePayload: (profile: TProfile) => TUpdatePayload;
  deriveUniversitySelection: (value: string) => string;
  hasText: (value: string) => boolean;
  getCollegeName: (profile: TProfile) => string;
  getCurrentAddress: (profile: TProfile) => {
    line1: string;
    landmark: string;
    region: string;
    pincode: string;
  };
  getPermanentAddress: (profile: TProfile) => {
    line1: string;
    landmark: string;
    region: string;
    pincode: string;
  };
  getResumeFilename: (profile: TProfile) => string;
  setSelectedUniversity: Dispatch<SetStateAction<string>>;
  setCopyCurrentAddress: Dispatch<SetStateAction<boolean>>;
};

type UseProfileDataResult = {
  loading: boolean;
  saving: boolean;
  uploadingResume: boolean;
  email: string;
  message: string | null;
  error: string | null;
  saveProfile: () => Promise<void>;
  uploadResume: (file: File) => Promise<void>;
  deleteResume: () => Promise<void>;
  downloadResume: () => Promise<void>;
};

export function useProfileData<TProfile, TUpdatePayload>({
  profile,
  setProfile,
  hydrateProfilePayload,
  buildProfileUpdatePayload,
  deriveUniversitySelection,
  hasText,
  getCollegeName,
  getCurrentAddress,
  getPermanentAddress,
  getResumeFilename,
  setSelectedUniversity,
  setCopyCurrentAddress,
}: UseProfileDataArgs<TProfile, TUpdatePayload>): UseProfileDataResult {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingResume, setUploadingResume] = useState(false);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    const loadProfile = async (showFatalErrors: boolean) => {
      try {
        const [userResult, profileResult] = await Promise.allSettled([
          fetch(apiUrl("/api/v1/users/me"), createAuthenticatedFetchInit({}, token)),
          fetch(apiUrl("/api/v1/users/me/profile"), createAuthenticatedFetchInit({}, token)),
        ]);

        let userError: string | null = null;
        let profileError: string | null = null;
        let hasFreshProfile = false;

        if (userResult.status === "fulfilled") {
          const userRes = userResult.value;
          const userPayload = (await userRes.json().catch(() => ({}))) as Record<string, unknown>;
          if (userRes.ok) {
            setEmail(typeof userPayload.email === "string" ? userPayload.email : "");
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
            setSelectedUniversity(deriveUniversitySelection(getCollegeName(nextProfile)));

            const currentAddress = getCurrentAddress(nextProfile);
            const permanentAddress = getPermanentAddress(nextProfile);
            setCopyCurrentAddress(
              hasText(currentAddress.line1) &&
                currentAddress.line1 === permanentAddress.line1 &&
                currentAddress.landmark === permanentAddress.landmark &&
                currentAddress.region === permanentAddress.region &&
                currentAddress.pincode === permanentAddress.pincode,
            );

            hasFreshProfile = true;
            setError(null);
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
  }, [
    router,
    setProfile,
    hydrateProfilePayload,
    deriveUniversitySelection,
    hasText,
    getCollegeName,
    getCurrentAddress,
    getPermanentAddress,
    setSelectedUniversity,
    setCopyCurrentAddress,
  ]);

  const saveProfile = useCallback(async () => {
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
      const res = await fetch(
        apiUrl("/api/v1/users/me/profile"),
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
      const payload = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        throw new Error(getApiErrorMessage(payload, "Unable to update profile"));
      }
      const nextProfile = hydrateProfilePayload(payload);
      setProfile(nextProfile);
      setSelectedUniversity(deriveUniversitySelection(getCollegeName(nextProfile)));
      setMessage("Profile updated successfully.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to update profile"));
    } finally {
      setSaving(false);
    }
  }, [
    profile,
    router,
    buildProfileUpdatePayload,
    hydrateProfilePayload,
    setProfile,
    deriveUniversitySelection,
    getCollegeName,
    setSelectedUniversity,
  ]);

  const uploadResume = useCallback(async (file: File) => {
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
      setProfile(hydrateProfilePayload(payload));
      setMessage("Resume uploaded and profile signals refreshed.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to upload resume"));
    } finally {
      setUploadingResume(false);
    }
  }, [router, setProfile, hydrateProfilePayload]);

  const deleteResume = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setUploadingResume(true);
    setMessage(null);
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
      setProfile(hydrateProfilePayload(payload));
      setMessage("Resume removed.");
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to remove resume"));
    } finally {
      setUploadingResume(false);
    }
  }, [router, setProfile, hydrateProfilePayload]);

  const downloadResume = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    setError(null);
    try {
      const res = await fetch(
        apiUrl("/api/v1/users/me/resume/download"),
        createAuthenticatedFetchInit({}, token),
      );
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(getApiErrorMessage(payload, "Unable to download resume"));
      }
      const blob = await res.blob();
      const link = document.createElement("a");
      const objectUrl = URL.createObjectURL(blob);
      link.href = objectUrl;
      link.download = getResumeFilename(profile) || "resume";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(getUnknownErrorMessage(err, "Unable to download resume"));
    }
  }, [router, profile, getResumeFilename]);

  return {
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
  };
}
