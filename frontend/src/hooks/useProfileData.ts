"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { apiUrl } from "@/lib/api";
import { clearAccessToken, createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { getApiErrorMessage, getUnknownErrorMessage } from "@/lib/error-utils";

type UseProfileDataArgs<TProfile, TUpdatePayload> = {
  profile: TProfile;
  setProfile: Dispatch<SetStateAction<TProfile>>;
  hydrateProfilePayload: (payload: Record<string, unknown>) => TProfile;
  buildProfileUpdatePayload: (profile: TProfile) => TUpdatePayload;
  deriveUniversitySelection: (value: string) => string;
  hasText: (value: string) => boolean;
  getCollegeName: (profile: TProfile) => string;
  // Region only. Street line, landmark and pincode were removed in the 2026-08-05
  // data-minimization pass: nothing read them, and a pincode alongside a college
  // name is enough to identify a student outright.
  getCurrentAddress: (profile: TProfile) => { region: string };
  getPermanentAddress: (profile: TProfile) => { region: string };
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

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit, timeoutMs = 3500): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

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

  // Snapshot of the profile exactly as the server last gave it to us. Anything
  // that differs from this is unsaved work the student typed.
  const lastServerProfileRef = useRef<string | null>(null);
  const profileRef = useRef(profile);

  // Mirrored in an effect rather than during render: assigning to a ref while
  // rendering is not safe under concurrent rendering.
  useEffect(() => {
    profileRef.current = profile;
  }, [profile]);

  const hasUnsavedEdits = useCallback((): boolean => {
    const baseline = lastServerProfileRef.current;
    if (baseline === null) {
      return false;
    }
    try {
      return JSON.stringify(profileRef.current) !== baseline;
    } catch {
      // Never let a serialisation problem decide to discard someone's typing.
      return true;
    }
  }, []);

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
          fetchWithTimeout(apiUrl("/api/v1/users/me"), createAuthenticatedFetchInit({}, token)),
          fetchWithTimeout(apiUrl("/api/v1/users/me/profile"), createAuthenticatedFetchInit({}, token)),
        ]);

        let userError: string | null = null;
        let profileError: string | null = null;
        let hasFreshProfile = false;

        // An expired or invalid session is not a profile error. Rendering the
        // raw API text left the user on a form that looked broken - every field
        // blank, completion 0%, and "Could not validate credentials" above it -
        // with no indication that signing in again was the fix. Tokens last 24
        // hours, so this is a routine state, not an exceptional one.
        const unauthorized =
          (userResult.status === "fulfilled" && userResult.value.status === 401) ||
          (profileResult.status === "fulfilled" && profileResult.value.status === 401);
        if (unauthorized) {
          clearAccessToken("expired");
          const returnTo = typeof window !== "undefined" ? window.location.pathname : "";
          router.replace(returnTo ? `/login?next=${encodeURIComponent(returnTo)}` : "/login");
          return;
        }

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
            // Baseline for the unsaved-work check. Set on every server hydrate,
            // including after a save, so a saved profile is not treated as dirty.
            try {
              lastServerProfileRef.current = JSON.stringify(nextProfile);
            } catch {
              lastServerProfileRef.current = null;
            }
            setSelectedUniversity(deriveUniversitySelection(getCollegeName(nextProfile)));

            const currentAddress = getCurrentAddress(nextProfile);
            const permanentAddress = getPermanentAddress(nextProfile);
            setCopyCurrentAddress(
              hasText(currentAddress.region) && currentAddress.region === permanentAddress.region,
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

    // Refresh on focus, but never over unsaved work. A student switching to
    // another app to copy a LinkedIn URL - the most ordinary thing that happens
    // on a phone in this form - used to come back to every typed field silently
    // reverted to the last server state, with no warning and no undo.
    const handleWindowFocus = () => {
      if (hasUnsavedEdits()) {
        return;
      }
      void loadProfile(false);
    };

    // Closing the tab mid-edit deserves a prompt for the same reason.
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (hasUnsavedEdits()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };

    window.addEventListener("focus", handleWindowFocus);
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("focus", handleWindowFocus);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [
    router,
    setProfile,
    hasUnsavedEdits,
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
      try {
        lastServerProfileRef.current = JSON.stringify(nextProfile);
      } catch {
        lastServerProfileRef.current = null;
      }
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
