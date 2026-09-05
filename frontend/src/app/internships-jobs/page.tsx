"use client";
import Sidebar from "@/components/Sidebar";
import AskAIPanel from "@/components/AskAIPanel";
import { OpportunityCardsSkeleton } from "@/components/LoadingSkeletons";
import React, { startTransition, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Bookmark, Calendar, ChevronDown, ExternalLink, EyeOff, MapPin, Send, X } from "lucide-react";
import Image from "next/image";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { logTrackedOpportunityEvent, useOpportunityFeedImpressions } from "@/lib/opportunity-feed-tracker";
/* classifyRoleTrack and matchesTrackFilter are deliberately not imported.
   Both ran here and both read `description`, which is the only reason this page
   ever downloaded the whole corpus. The API classifies and filters now; the
   filter labels below are still shared from this module so the chips and the
   server vocabulary cannot drift. */
import {
    NON_TECHNICAL_FILTERS,
    TECHNICAL_FILTERS,
    type RoleTrack,
    type TrackFilter,
} from "@/lib/role-classification";

/* Placement pills. The four non-"all" keys mirror
   backend/app/services/opportunity_placement.py::FEED_CATEGORIES and must stay in
   step with it — the backend computes membership, this only renders it. */
const PLACEMENT_TABS = [
    { key: "all", label: "All" },
    { key: "india", label: "India" },
    { key: "remote", label: "Remote" },
    { key: "hybrid", label: "Hybrid" },
    { key: "international", label: "International" },
] as const;

type PlacementKey = (typeof PLACEMENT_TABS)[number]["key"];

interface Opportunity {
    id: string;
    title: string;
    description: string;
    url: string;
    opportunity_type: string;
    university: string;
    domain: string;
    source?: string;
    canonical_key?: string;
    location?: string;
    work_mode?: string;
    /* Placement pills computed by the backend
       (services/opportunity_placement.py), not derived here. work_mode is null on
       73% of rows and location on 38%, so the categories are recovered from
       location, body text and source together — logic that has to stay in one
       place, and the read path is mid-migration between Mongo and Postgres.
       Non-exclusive: a remote internship in Bengaluru carries both india and
       remote. May be empty when nothing places the listing. */
    feed_categories?: string[];
    stipend?: string;
    eligibility?: string;
    batch_years?: number[];
    ppo_available?: string;
    trust_status?: string;
    trust_score?: number;
    risk_score?: number;
    risk_reasons?: string[];
    verification_evidence?: string[];
    created_at?: string;
    updated_at?: string;
    last_seen_at?: string;
    deadline?: string;
    ranking_mode?: string;
    experiment_key?: string;
    experiment_variant?: string;
    rank_position?: number;
    match_score?: number;
    match_reasons?: string[];
    eligibility_warnings?: string[];
    model_version_id?: string;
}

const NOTICE_AUTO_DISMISS_MS = 10_000;
const FEED_REFRESH_MS = 60 * 1000;
const FEED_RETRY_MS = 15 * 1000;
// Must exceed the Next proxy's own upstream timeout, or the client abandons a
// request the proxy is still happily waiting on and silently drops to the
// unpersonalised list. It was 2500ms against a 5000ms proxy.
const PERSONALIZED_FETCH_TIMEOUT_MS = 8000;
const FALLBACK_FETCH_TIMEOUT_MS = 8000;
const COMPETITIVE_KEYWORDS = [
    "hackathon",
    "competition",
    "challenge",
    "quiz",
    "conference",
    "workshop",
    "bootcamp",
    "webinar",
    "buildathon",
    "ctf",
];
/* Rows requested per page.

   The grid used to map over every filtered listing, so switching a chip asked
   React to reconcile up to 1500 card components in one commit. Worse, getting
   those rows cost 3.36 MB of Postgres egress per request. Discrete pages fix
   both: one page is one small query and one small commit. */
/** Floor between two identical feed requests. Below the 60s poll, above a render. */
const MIN_REFETCH_MS = 10_000;
const DEFAULT_PER_PAGE = 12;
/** Offered in the "Records per page" control. Capped at 100 by the API. */
const PER_PAGE_OPTIONS = [12, 24, 48, 96];

const CAREER_KEYWORDS = ["internship", "intern", "job", "hiring", "developer", "engineer", "lead"];

/* Deadlines render identically on the server and in the browser.

   These called toLocaleDateString(undefined, ...), and `undefined` means "use
   whatever locale the runtime defaults to". Node resolves that differently from
   a student's browser, and the timezone differs too, so the server sent one
   string and React rendered another - which is React error #418, the hydration
   mismatch that was in the console on this page.

   Pinned to en-IN because the corpus is India-focused, and to UTC because a
   deadline is a date rather than a moment: formatting a midnight-UTC deadline in
   a local timezone can move it a day in either direction. */
const DEADLINE_LOCALE = "en-IN";

function formatDeadline(
    value: string | null | undefined,
    options: Intl.DateTimeFormatOptions,
): string | null {
    if (!value) return null;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return null;
    return parsed.toLocaleDateString(DEADLINE_LOCALE, { timeZone: "UTC", ...options });
}

const buildOpportunitiesSignature = (items: Opportunity[]): string =>
    items
        .map(
            (item) =>
                `${item.id}:${item.created_at || ""}:${item.updated_at || ""}:${item.last_seen_at || ""}:${
                    item.deadline || ""
                }:${item.title}:${item.source || ""}`
        )
        .join("|");

async function fetchJsonWithTimeout<T>(
    path: string,
    init: RequestInit,
    timeoutMs: number,
): Promise<T | null> {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(apiUrl(path), {
            ...init,
            signal: controller.signal,
        });
        if (!response.ok) {
            return null;
        }
        return (await response.json()) as T;
    } catch {
        return null;
    } finally {
        window.clearTimeout(timeoutId);
    }
}

/* A description is only worth showing if it actually describes the role.
   Scrapers fall back to boilerplate ("Opportunity indexed from Naukri.") and
   sometimes capture a site's own navigation; presenting either as the job
   description misleads the reader more than showing nothing. When the text does
   not clear the bar, point at the employer's posting - the authoritative
   version - instead of inventing confidence we do not have. */
const DESC_PLACEHOLDER_RE =
    /(opportunity indexed from|indexed from|discovered on the official|curated .{0,30}list entry|remote-friendly role indexed|no description)/i;
const DESC_CHROME_RE =
    /(post a job|sign in|privacy policy|terms of use|quick links|how it works|career center|all rights reserved)/gi;

function isUsableDescription(text?: string | null): boolean {
    const value = String(text ?? "").trim();
    if (value.length < 120) return false;
    if (DESC_PLACEHOLDER_RE.test(value)) return false;
    const chrome = (value.match(DESC_CHROME_RE) || []).length;
    if (chrome >= 3) return false;
    const digits = (value.match(/\d/g) || []).length;
    return !(chrome >= 2 && digits > value.length * 0.04);
}

export default function InternshipsJobsPage() {
    const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
    const [loading, setLoading] = useState(true);
    const [notice, setNotice] = useState<string | null>(null);

    // Transient notices must clear themselves. "Saved to your Applications.
    // Redirecting..." stayed on screen indefinitely when the redirect did not
    // happen, so the page kept telling the student an action was in flight long
    // after it had finished. Persistent conditions re-set the notice on their own
    // polling cycle, so they survive this timer.
    useEffect(() => {
      if (!notice) {
        return;
      }
      const timer = window.setTimeout(() => setNotice(null), NOTICE_AUTO_DISMISS_MS);
      return () => window.clearTimeout(timer);
    }, [notice]);

    const [applyingId, setApplyingId] = useState<string | null>(null);
    // "all" keeps the previous behaviour available; the two tracks split a feed
    // that otherwise showed a commerce student backend roles and an engineering
    // student sales roles.
    const [roleTrack, setRoleTrack] = useState<RoleTrack | "all">("all");
    // Placement filter, independent of the role track: a student can want
    // technical + remote at the same time. Single-select because the pills answer
    // one question ("where do I want to work"), and the categories overlap, so
    // multi-select would raise "does India + Remote mean both or either" with no
    // obvious answer.
    const [placement, setPlacement] = useState<PlacementKey>("all");
    // Full posting lives in a detail view rather than on the card, so the grid
    // stays scannable: the description was the tallest element on every card and
    // pushed the actions below the fold.
    const [detailOpp, setDetailOpp] = useState<Opportunity | null>(null);
    const [trackKeywords, setTrackKeywords] = useState<string[]>([]);
    const [filterMenuOpen, setFilterMenuOpen] = useState(false);
    const [placementMenuOpen, setPlacementMenuOpen] = useState(false);
    /* The key of the request currently in flight.

       Several things ask the feed to refresh - the filter/page effect, the
       polling interval, the visibility handler - and on mount more than one of
       them fires within the same few hundred milliseconds. That was harmless
       when the whole corpus was fetched once and cached; now every duplicate is
       a real query against Postgres, and worse, the concurrent ones queue behind
       each other in a small connection pool until the 8s client timeout aborts
       them. An aborted fetch leaves the feed empty, which switches the poller
       from 60s to its 15s retry, which fires more of them.

       Collapsing identical in-flight requests breaks that loop at the source. */
    const inFlightKeyRef = useRef<string | null>(null);
    /* When the same request last completed, so an identical one cannot be issued
       again immediately.

       The in-flight guard alone only collapses requests that overlap. Measured in
       the browser, something re-triggers the fetch on nearly every render, so the
       requests simply queued nose to tail instead: eleven of them in 66 seconds,
       each starting as the previous finished. A floor caps that regardless of how
       many triggers there are, without me having to find every one.

       Keyed by the query string, so changing page or filter is never delayed -
       that is a different key and goes out immediately. Only a repeat of the
       identical request waits. */
    const lastFetchRef = useRef<{ key: string; at: number }>({ key: "", at: 0 });
    const [page, setPage] = useState(1);
    const [perPage, setPerPage] = useState(DEFAULT_PER_PAGE);
    const [totalCount, setTotalCount] = useState(0);
    const [pageCount, setPageCount] = useState(1);
    /* Filter counts, computed by the API with two GROUP BY queries. Deriving
       them in the browser meant downloading the corpus to count it. */
    const [facets, setFacets] = useState<{
        tracks?: { all?: number; technical?: number; non_technical?: number };
        placements?: { all?: number; india?: number; remote?: number; hybrid?: number; international?: number };
    } | null>(null);
    const [savedOpportunityIds, setSavedOpportunityIds] = useState<Record<string, boolean>>({});
    const [hiddenOpportunityIds, setHiddenOpportunityIds] = useState<Record<string, boolean>>({});
    const [imageFallbackMap, setImageFallbackMap] = useState<Record<string, boolean>>({});
    const opportunitiesSignatureRef = useRef<string>("");
    const scraperTriggerAttemptedRef = useRef(false);

    const triggerLiveRefresh = useEffectEvent(async () => {
        const token = getAccessToken();
        if (!token) {
            return;
        }
        try {
            await fetch(
                apiUrl("/api/v1/opportunities/trigger-scraper"),
                createAuthenticatedFetchInit(
                    {
                        method: "POST",
                    },
                    token,
                ),
            );
        } catch (error) {
            const message = error instanceof Error ? error.message : "unknown error";
            console.warn(`[Opportunities] Trigger scraper failed: ${message}`);
        }
    });

    /* Back to page 1 whenever the filter changes.

       Page 7 of an unfiltered feed is not page 7 of a filtered one - narrowing
       to a speciality with two pages while sitting on page 7 asks the API for
       an offset past the end and renders an empty grid that looks like a bug.

       Adjusted during render rather than in an effect: an effect would fire a
       request for the stale page first, then a second one for page 1, which is
       two round trips and a flash of the wrong result. */
    const activeFilterSignature = `${roleTrack}|${placement}|${[...trackKeywords].sort().join(",")}`;
    const [appliedFilterSignature, setAppliedFilterSignature] = useState(activeFilterSignature);
    if (appliedFilterSignature !== activeFilterSignature) {
        setAppliedFilterSignature(activeFilterSignature);
        setPage(1);
    }

    /** True when any filter narrows the feed, so an empty result is explainable. */
    const hasActiveFilter =
        roleTrack !== "all" || placement !== "all" || trackKeywords.length > 0;

    const fetchOpportunities = useEffectEvent(async () => {
        // Whether THIS call is the one that claimed the in-flight slot. A
        // duplicate returns early, but `finally` still runs, so without this it
        // would clear a key it never set and release the guard while the real
        // request was still open - which made the guard do nothing at all.
        let ownsInFlight = false;
        // requestKey is built inside the try; the finally needs it too.
        let requestKeyForRelease = "";
        try {
            /* One page, filtered and counted by the API.

               This previously asked for limit=1500 and filtered in the browser,
               which moved 3.36 MB out of Postgres per request. The filters are
               query parameters now, so narrowing the list makes the response
               smaller instead of leaving it unchanged. */
            const params = new URLSearchParams({
                portal: "career",
                page: String(page),
                per_page: String(perPage),
            });
            if (roleTrack !== "all") params.set("role_track", roleTrack);
            if (placement !== "all") params.set("placement", placement);
            if (trackKeywords.length > 0) params.set("specialities", trackKeywords.join(","));

            const requestKey = params.toString();
            if (inFlightKeyRef.current === requestKey) {
                return;
            }
            const previous = lastFetchRef.current;
            if (previous.key === requestKey && Date.now() - previous.at < MIN_REFETCH_MS) {
                return;
            }
            inFlightKeyRef.current = requestKey;
            requestKeyForRelease = requestKey;
            ownsInFlight = true;

            const token = getAccessToken();
            const paged = await fetchJsonWithTimeout<{
                items: Opportunity[];
                total: number;
                pages: number;
                facets: Record<string, Record<string, number>>;
            }>(
                `/api/v1/opportunities/page?${params.toString()}`,
                token ? createAuthenticatedFetchInit({}, token) : { credentials: "include" },
                token ? PERSONALIZED_FETCH_TIMEOUT_MS : FALLBACK_FETCH_TIMEOUT_MS,
            );
            if (paged && Array.isArray(paged.items)) {
                const data: Opportunity[] = paged.items.map((item, idx) => ({
                    ...item,
                    ranking_mode: item.ranking_mode || "baseline",
                    experiment_key: item.experiment_key || "ranking_mode",
                    experiment_variant: item.experiment_variant || item.ranking_mode || "baseline",
                    rank_position: item.rank_position ?? (page - 1) * perPage + idx + 1,
                }));
                const nextSignature = buildOpportunitiesSignature(data);
                if (nextSignature !== opportunitiesSignatureRef.current) {
                    opportunitiesSignatureRef.current = nextSignature;
                    startTransition(() => {
                        setOpportunities(data);
                    });
                }
                setTotalCount(paged.total ?? 0);
                setPageCount(Math.max(1, paged.pages ?? 1));
                setFacets(paged.facets ?? null);
                if (data.length === 0 && (paged.total ?? 0) === 0 && !hasActiveFilter) {
                    // Empty with no filter applied means the corpus is empty, not
                    // that the filter is narrow. Only then is a scrape worth
                    // triggering - doing it on a narrow filter kicked the scraper
                    // every time someone picked an unpopular speciality.
                    setNotice("Refreshing live opportunities...");
                    if (!scraperTriggerAttemptedRef.current) {
                        scraperTriggerAttemptedRef.current = true;
                        void triggerLiveRefresh();
                    }
                } else {
                    scraperTriggerAttemptedRef.current = false;
                    setNotice(null);
                }
                return;
            }

            /* No 1500-row fallback any more.

               The anonymous path used to fetch the whole corpus, so an
               unauthenticated visit still cost 3.36 MB of Postgres egress and
               quietly undid the paging above. /page serves both paths. */
            // fetchJsonWithTimeout swallows the body on failure, so the specific
            // upstream detail is no longer available here. One honest message
            // beats guessing which of several causes applied.
            setNotice("Live opportunities are temporarily unavailable. Retrying...");
            if (!scraperTriggerAttemptedRef.current) {
                scraperTriggerAttemptedRef.current = true;
                void triggerLiveRefresh();
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : "unknown error";
            console.warn(`[Opportunities] Fetch failed: ${message}`);
            setNotice("Backend API is unavailable. Retrying...");
            if (!scraperTriggerAttemptedRef.current) {
                scraperTriggerAttemptedRef.current = true;
                void triggerLiveRefresh();
            }
        } finally {
            // Released here, not at the return sites. The function exits from
            // several places - the success path returns early, the empty path
            // falls through, the catch handles a thrown error - and a key left
            // set on any one of them would block every later refresh of the same
            // page for the life of the component.
            if (ownsInFlight) {
                inFlightKeyRef.current = null;
                lastFetchRef.current = { key: requestKeyForRelease, at: Date.now() };
            }
            setLoading(false);
        }
    });

    const logOpportunityEvent = useCallback(
        async (opportunity: Opportunity, interactionType: "impression" | "click" | "save" | "apply" | "dismiss") => {
            await logTrackedOpportunityEvent(opportunity, interactionType, {
                surface: "internships_jobs_page",
                activeTab: roleTrack,
            });
        },
        [roleTrack]
    );

    useEffect(() => {
        const timeoutId = window.setTimeout(() => {
            // Deliberately no fetchOpportunities() here. The effect below already
            // runs on mount - page, perPage and the filters all have initial
            // values - so calling it here too fired two identical requests for
            // every page view. Verified in the browser's network panel: each
            // navigation produced a matched pair. Harmless before paging, when
            // the corpus was fetched once; now that a request is the unit of
            // egress, it was doubling the thing this work exists to reduce.
            void triggerLiveRefresh();
        }, 0);
        return () => window.clearTimeout(timeoutId);
    }, []);

    /* Refetch whenever the page, the page size or any filter changes.

       The filters are server-side now, so this is the whole mechanism: there is
       no local corpus left to re-filter. Each of these produces one ~46 KB
       request rather than re-slicing 3.36 MB already in memory. */
    useEffect(() => {
        // react-hooks/set-state-in-effect fires because fetchOpportunities sets
        // state. The rule targets state derived from other state, which should be
        // computed during render. This is the other case: synchronising with an
        // external system, where the server is the source of truth and the
        // request is the point. There is no local corpus left to derive from.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void fetchOpportunities();
    }, [page, perPage, roleTrack, placement, trackKeywords]);

    useEffect(() => {
        const refreshMs = opportunities.length > 0 ? FEED_REFRESH_MS : FEED_RETRY_MS;
        const interval = window.setInterval(() => {
            void fetchOpportunities();
        }, refreshMs);
        return () => window.clearInterval(interval);
    }, [opportunities.length]);

    useEffect(() => {
        const onVisibilityChange = () => {
            if (document.visibilityState === "visible") {
                void fetchOpportunities();
            }
        };
        const onFocus = () => {
            void fetchOpportunities();
        };
        document.addEventListener("visibilitychange", onVisibilityChange);
        window.addEventListener("focus", onFocus);
        return () => {
            document.removeEventListener("visibilitychange", onVisibilityChange);
            window.removeEventListener("focus", onFocus);
        };
    }, []);

    const filtered = useMemo(() => {
        /* Collapse repeated ids before anything else looks at the list.
           The corpus carries a handful of rows sharing one id (the migration
           dropped the unique constraint on the legacy identifier), and the cards
           are keyed by that id. Duplicate React keys break reconciliation: the
           track filter computed the right subset - the badge read "433 live" -
           while all 797 cards stayed on screen, so every chip looked dead.
           Removing the repeats fixes the filters and stops the same posting
           appearing twice. */
        const seenIds = new Set<string>();
        const source = opportunities.filter((opportunity) => {
            if (hiddenOpportunityIds[opportunity.id]) {
                return false;
            }
            const id = String(opportunity.id ?? "");
            if (id && seenIds.has(id)) {
                return false;
            }
            if (id) {
                seenIds.add(id);
            }
            return true;
        });
        const getSortTimestamp = (opportunity: Opportunity) =>
            new Date(opportunity.last_seen_at || opportunity.updated_at || opportunity.created_at || 0).getTime();
        return [...source].sort(
            (a, b) => getSortTimestamp(b) - getSortTimestamp(a)
        );
    }, [hiddenOpportunityIds, opportunities]);

    const grouped = useMemo(() => {
        const matchesKeyword = (value: string, keywords: string[]) =>
            keywords.some((keyword) => value.includes(keyword));

        const groups: Record<"competitive" | "career" | "other", Opportunity[]> = {
            competitive: [],
            career: [],
            other: [],
        };

        for (let idx = 0; idx < filtered.length; idx += 1) {
            const opportunity: Opportunity = {
                ...filtered[idx],
                rank_position: filtered[idx].rank_position ?? idx + 1,
            };
            const typeValue = (opportunity.opportunity_type || "").toLowerCase().trim();
            const titleValue = (opportunity.title || "").toLowerCase().trim();
            const descriptionValue = (opportunity.description || "").toLowerCase().trim();
            const haystack = `${typeValue} ${titleValue} ${descriptionValue}`;

            if (matchesKeyword(haystack, CAREER_KEYWORDS)) {
                groups.career.push(opportunity);
                continue;
            }

            if (matchesKeyword(haystack, COMPETITIVE_KEYWORDS)) {
                groups.competitive.push(opportunity);
                continue;
            }

            groups.other.push(opportunity);
        }

        return groups;
    }, [filtered]);

    // "All roles" offers every speciality, so a student who has not picked a
    // track can still narrow by interest.
    const trackFilters: TrackFilter[] = useMemo(
        () =>
            roleTrack === "technical"
                ? TECHNICAL_FILTERS
                : roleTrack === "non_technical"
                  ? NON_TECHNICAL_FILTERS
                  : [...TECHNICAL_FILTERS, ...NON_TECHNICAL_FILTERS],
        [roleTrack],
    );


    /* Server-driven paging. The filter, the counts and the slice all happen in
       SQL now.

       This block used to classify every listing in the browser and filter the
       whole corpus locally, which is why the page fetched all ~1600 active rows
       at 3.36 MB per request. A 5.5 GB monthly Postgres egress allowance covers
       about 1,600 of those, and that is how the Supabase project got restricted
       at 16.86 GB with one developer using it. One page is ~46 KB. */
    const visibleOpportunities = grouped.career;

    const trackCounts = {
        all: facets?.tracks?.all ?? 0,
        technical: facets?.tracks?.technical ?? 0,
        non_technical: facets?.tracks?.non_technical ?? 0,
    };

    /* Counts respect the role track but not the placement pill itself, so each
       pill shows how many listings it would yield rather than how many are
       showing now. They deliberately sum to more than "All": a remote internship
       in Bengaluru is counted under both India and Remote. */
    const placementCounts = {
        all: facets?.placements?.all ?? 0,
        india: facets?.placements?.india ?? 0,
        remote: facets?.placements?.remote ?? 0,
        hybrid: facets?.placements?.hybrid ?? 0,
        international: facets?.placements?.international ?? 0,
    };

    const trackerContext = useMemo(
        () => ({ surface: "internships_jobs_page", activeTab: roleTrack }),
        [roleTrack]
    );
    /* One page is exactly what was put on screen, so this is now the honest
       impression set. It used to be passed every listing the filter matched -
       up to 1500 - when the student had seen a couple of dozen, which inflated
       the denominator of every CTR the ranking work is measured on. */
    useOpportunityFeedImpressions(visibleOpportunities, trackerContext);

    const handleSave = async (opportunity: Opportunity) => {
        setSavedOpportunityIds((current) => ({ ...current, [opportunity.id]: true }));
        await logOpportunityEvent(opportunity, "save");
    };

    const handleHide = (opportunity: Opportunity) => {
        setHiddenOpportunityIds((current) => ({ ...current, [opportunity.id]: true }));
        void logOpportunityEvent(opportunity, "dismiss");
    };

    const handleApply = async (opportunity: Opportunity) => {
        const token = getAccessToken();
        if (!token) {
            setNotice("Sign in to use one-click application.");
            return;
        }

        setApplyingId(opportunity.id);
        setNotice(null);
        try {
            const query = new URLSearchParams({
                ranking_mode: opportunity.ranking_mode || "baseline",
                experiment_key: opportunity.experiment_key || "ranking_mode",
                experiment_variant: opportunity.experiment_variant || opportunity.ranking_mode || "baseline",
                rank_position: String(opportunity.rank_position ?? 1),
            });
            if (typeof opportunity.match_score === "number") {
                query.set("match_score", String(opportunity.match_score));
            }
            if (opportunity.model_version_id) {
                query.set("model_version_id", opportunity.model_version_id);
            }
            const res = await fetch(
                apiUrl(`/api/v1/applications/${opportunity.id}?${query.toString()}`),
                createAuthenticatedFetchInit(
                    {
                        method: "POST",
                    },
                    token,
                ),
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Application failed");
            }
            setNotice("Saved to your Applications. Redirecting...");
            if (typeof window !== "undefined") {
                if (opportunity.url) {
                    window.location.assign(opportunity.url);
                    return;
                }
                setNotice("Saved to your Applications.");
                return;
            }
        } catch (error: unknown) {
            setNotice(error instanceof Error ? error.message : "Could not submit application.");
        } finally {
            setApplyingId(null);
        }
    };

    const TYPE_IMAGE_MAP: Record<string, string> = {
        bounty: "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=1400&q=80",
        bounties: "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?auto=format&fit=crop&w=1400&q=80",
        grant: "https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&w=1400&q=80",
        hackathon: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1400&q=80",
        hackathons: "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1400&q=80",
        conference: "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
        conferences: "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
        quiz: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1400&q=80",
        quizzes: "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?auto=format&fit=crop&w=1400&q=80",
        challenge: "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=1400&q=80",
        competition: "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1400&q=80",
        workshop: "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
        internship: "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1400&q=80",
        hiring: "https://images.unsplash.com/photo-1520607162513-77705c0f0d4a?auto=format&fit=crop&w=1400&q=80",
    };

    const DOMAIN_IMAGE_MAP: Record<string, string> = {
        "ai and machine learning": "https://images.unsplash.com/photo-1532619675605-1ede6c2ed2b0?auto=format&fit=crop&w=1400&q=80",
        engineering: "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
        marketing: "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1400&q=80",
        "business and operations": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=1400&q=80",
        "sales and support": "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&w=1400&q=80",
        "human resources": "https://images.unsplash.com/photo-1521791136064-7986c2920216?auto=format&fit=crop&w=1400&q=80",
        "design and creative": "https://images.unsplash.com/photo-1561070791-2526d30994b5?auto=format&fit=crop&w=1400&q=80",
        education: "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=1400&q=80",
        other: "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1400&q=80",
        finance: "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1400&q=80",
        "data science": "https://images.unsplash.com/photo-1516321497487-e288fb19713f?auto=format&fit=crop&w=1400&q=80",
        law: "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?auto=format&fit=crop&w=1400&q=80",
        biomedical: "https://images.unsplash.com/photo-1579154204601-01588f351e67?auto=format&fit=crop&w=1400&q=80",
        healthcare: "https://images.unsplash.com/photo-1579154204601-01588f351e67?auto=format&fit=crop&w=1400&q=80",
    };

    const FALLBACK_IMAGE =
        "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=1400&q=80";

    const normalize = (value?: string) => (value || "").toLowerCase().trim();

    const findMappedImage = (value: string, map: Record<string, string>) => {
        for (const [keyword, image] of Object.entries(map)) {
            if (value.includes(keyword)) {
                return image;
            }
        }
        return null;
    };

    const getCompetitionImage = (opp: Opportunity) => {
        const typeValue = normalize(opp.opportunity_type);
        const domainValue = normalize(opp.domain);
        const titleValue = normalize(opp.title);

        return (
            findMappedImage(typeValue, TYPE_IMAGE_MAP) ||
            findMappedImage(domainValue, DOMAIN_IMAGE_MAP) ||
            findMappedImage(titleValue, TYPE_IMAGE_MAP) ||
            FALLBACK_IMAGE
        );
    };

    const formatSourceLabel = (source?: string) => {
        const normalized = (source || "source").replace(/_/g, " ").trim();
        return normalized
            .split(" ")
            .filter(Boolean)
            .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
            .join(" ");
    };

    const renderTrustBadge = (opp: Opportunity) => {
        const isVerified = (opp.trust_status || "").toLowerCase() === "verified";
        return (
            <span
                style={{
                    fontSize: "0.72rem",
                    padding: "0.22rem 0.58rem",
                    borderRadius: "999px",
                    background: isVerified ? "#dcfce7" : "#fff7d6",
                    color: "#111111",
                    fontWeight: 900,
                    textTransform: "uppercase",
                    border: `2px solid ${isVerified ? "#86efac" : "#facc15"}`,
                }}
            >
                {isVerified ? "Signals found" : "No signals found"}
            </span>
        );
    };

    const trustSummary = (opp: Opportunity) => {
        const trustScore = Math.max(0, Math.min(100, Number(opp.trust_score || 0)));
        const evidence = Array.isArray(opp.verification_evidence) ? opp.verification_evidence[0] : null;
        return {
            scoreLabel: `Risk heuristic: ${trustScore}/100`,
            evidenceLabel: evidence || "No corroborating signal was found for this listing\u2019s host or organiser.",
        };
    };

    const metadataChips = (opp: Opportunity) =>
        [
            opp.location ? `Location: ${opp.location}` : null,
            opp.work_mode ? opp.work_mode : null,
            opp.stipend ? `Stipend: ${opp.stipend}` : null,
            opp.batch_years && opp.batch_years.length > 0 ? `Batch: ${opp.batch_years.join(", ")}` : null,
            opp.ppo_available ? `PPO: ${opp.ppo_available}` : null,
        ].filter(Boolean) as string[];

    const renderMatchDetails = (opp: Opportunity) => {
        const matchReasons = (opp.match_reasons || [])
            .filter((reason) => !/(learned ranker|top model features|staged rollout|fallback)/i.test(reason))
            .slice(0, 2);
        const eligibilityWarnings = (opp.eligibility_warnings || []).slice(0, 1);
        if (matchReasons.length === 0 && eligibilityWarnings.length === 0) {
            return null;
        }

        return (
            <div style={{ display: "grid", gap: "0.4rem", padding: "0.7rem", borderRadius: "var(--radius-sm)", background: "var(--bg-surface-hover)", border: "1px solid var(--border-subtle)" }}>
                {matchReasons.length > 0 ? (
                    <div>
                        <strong style={{ fontSize: "0.82rem" }}>Why this matches you</strong>
                        <ul style={{ margin: "0.28rem 0 0", paddingLeft: "1.05rem", color: "var(--text-secondary)", fontSize: "0.84rem" }}>
                            {matchReasons.map((reason) => <li key={reason}>{reason}</li>)}
                        </ul>
                    </div>
                ) : null}
                {eligibilityWarnings.map((warning) => (
                    <span key={warning} style={{ color: "var(--text-secondary)", fontSize: "0.82rem", fontWeight: 700 }}>{warning}</span>
                ))}
            </div>
        );
    };

    const renderCompetitiveCard = (opp: Opportunity, idx: number) => {
        const imageUrl = imageFallbackMap[opp.id] ? FALLBACK_IMAGE : getCompetitionImage(opp);
        const trust = trustSummary(opp);
        const details = metadataChips(opp);
        return (
            <motion.article
                key={`${opp.id ?? "row"}-${idx}`}
                initial={{ opacity: 0, scale: 0.96, y: 24 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="card-panel"
                style={{
                    padding: 0,
                    display: "grid",
                    gridTemplateColumns: "minmax(150px, 190px) minmax(0, 1fr)",
                    minHeight: "240px",
                    overflow: "hidden",
                    background:
                        "linear-gradient(135deg, color-mix(in srgb, var(--brand-accent) 22%, transparent), var(--bg-surface) 55%)",
                }}
                whileHover={{ y: -5, boxShadow: "var(--shadow-md)", borderColor: "var(--brand-primary)" }}
            >
                <div
                    style={{
                        position: "relative",
                        minHeight: "100%",
                        borderRight: "2px solid var(--border-subtle)",
                        background: "#111111",
                    }}
                >
                    <Image
                        src={imageUrl}
                        alt={`${opp.opportunity_type || "Opportunity"} banner`}
                        fill
                        sizes="(max-width: 768px) 100vw, 190px"
                        onError={() => {
                            if (!imageFallbackMap[opp.id]) {
                                setImageFallbackMap((prev) => ({ ...prev, [opp.id]: true }));
                            }
                        }}
                        style={{ objectFit: "cover" }}
                    />
                    <div
                        style={{
                            position: "absolute",
                            inset: 0,
                            background: "linear-gradient(180deg, rgba(0,0,0,0.08) 0%, rgba(0,0,0,0.56) 100%)",
                        }}
                    />
                    <div
                        style={{
                            position: "absolute",
                            left: "1rem",
                            bottom: "1rem",
                            display: "flex",
                            flexDirection: "column",
                            gap: "0.5rem",
                        }}
                    >
                        <span
                            style={{
                                display: "inline-flex",
                                alignItems: "center",
                                width: "fit-content",
                                background: "var(--brand-primary)",
                                color: "#000000",
                                padding: "0.35rem 0.7rem",
                                borderRadius: "var(--radius-sm)",
                                border: "2px solid #000000",
                                fontSize: "0.75rem",
                                fontWeight: 900,
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                            }}
                        >
                            Event Track
                        </span>
                        <span style={{ color: "#ffffff", fontWeight: 700, fontSize: "0.85rem" }}>
                            {opp.deadline
                                ? `Closes ${formatDeadline(opp.deadline, { month: "short", day: "numeric" })}`
                                : "Rolling basis"}
                        </span>
                    </div>
                </div>
                <div style={{ padding: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem" }}>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
                        <span
                            style={{
                                fontSize: "0.75rem",
                                padding: "0.25rem 0.6rem",
                                borderRadius: "999px",
                                background: "#ffffff",
                                color: "#000000",
                                fontWeight: 900,
                                textTransform: "uppercase",
                                border: "2px solid var(--border-subtle)",
                            }}
                        >
                            {opp.opportunity_type || "Opportunity"}
                        </span>
                        <span
                            style={{
                                fontSize: "0.75rem",
                                padding: "0.25rem 0.6rem",
                                borderRadius: "999px",
                                background: "color-mix(in srgb, var(--brand-accent) 80%, white 20%)",
                                color: "#000000",
                                fontWeight: 800,
                                textTransform: "uppercase",
                                border: "2px solid var(--border-subtle)",
                            }}
                        >
                            {formatSourceLabel(opp.source)}
                        </span>
                        {renderTrustBadge(opp)}
                    </div>

                    <div>
                        <h2
                            style={{
                                fontSize: "1.4rem",
                                marginBottom: "0.55rem",
                                color: "var(--text-primary)",
                                lineHeight: 1.2,
                                fontWeight: 900,
                            }}
                        >
                            {opp.title}
                        </h2>
                        <p
                            style={{
                                color: "var(--text-secondary)",
                                fontSize: "0.95rem",
                                display: "-webkit-box",
                                WebkitLineClamp: 3,
                                WebkitBoxOrient: "vertical",
                                overflow: "hidden",
                                fontWeight: 500,
                            }}
                        >
                            {opp.description}
                        </p>
                        <div style={{ marginTop: "0.65rem", display: "grid", gap: "0.18rem" }}>
                            <div style={{ fontSize: "0.8rem", fontWeight: 800, color: "var(--text-primary)" }}>
                                {trust.scoreLabel}
                            </div>
                            <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", fontWeight: 600 }}>
                                {trust.evidenceLabel}
                            </div>
                        </div>
                        {details.length > 0 ? (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", marginTop: "0.7rem" }}>
                                {details.map((chip) => (
                                    <span
                                        key={chip}
                                        style={{
                                            fontSize: "0.74rem",
                                            padding: "0.22rem 0.55rem",
                                            borderRadius: "999px",
                                            background: "var(--bg-surface-hover)",
                                            border: "1px solid var(--border-subtle)",
                                            fontWeight: 700,
                                            color: "var(--text-secondary)",
                                        }}
                                    >
                                        {chip}
                                    </span>
                                ))}
                            </div>
                        ) : null}
                        {renderMatchDetails(opp)}
                    </div>

                    <div
                        style={{
                            marginTop: "auto",
                            display: "flex",
                            justifyContent: "space-between",
                            gap: "1rem",
                            alignItems: "end",
                            borderTop: "2px solid var(--border-subtle)",
                            paddingTop: "1rem",
                        }}
                    >
                        <div style={{ display: "grid", gap: "0.45rem" }}>
                            <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.9rem", fontWeight: 700 }}>
                                <MapPin size={14} /> {opp.university || "Global"}
                            </span>
                            <span style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.9rem", color: "var(--text-secondary)", fontWeight: 700 }}>
                                <Calendar size={14} />
                                {opp.deadline
                                    ? formatDeadline(opp.deadline, { month: "short", day: "numeric", year: "numeric" })
                                    : "Rolling Basis"}
                            </span>
                        </div>
                        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", justifyContent: "end" }}>
                            <button
                                className="btn-primary"
                                style={{ padding: "0.7rem 1.1rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.4rem", border: "2px solid #000000" }}
                                onClick={() => void handleApply(opp)}
                                disabled={applyingId === opp.id}
                            >
                                <Send size={14} />
                                {applyingId === opp.id ? "Joining..." : "Join"}
                            </button>
                            <button
                                className="btn-secondary"
                                style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                                onClick={() => void handleSave(opp)}
                                disabled={Boolean(savedOpportunityIds[opp.id])}
                            >
                                <Bookmark size={14} />
                                {savedOpportunityIds[opp.id] ? "Saved" : "Save"}
                            </button>
                            <button
                                className="btn-secondary"
                                type="button"
                                style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                                onClick={() => handleHide(opp)}
                                aria-label={`Hide ${opp.title}`}
                            >
                                <EyeOff size={14} /> Hide
                            </button>
                        </div>
                    </div>
                </div>
            </motion.article>
        );
    };

    const renderCareerCard = (opp: Opportunity, idx: number) => {
        const imageUrl = imageFallbackMap[opp.id] ? FALLBACK_IMAGE : getCompetitionImage(opp);
        const trust = trustSummary(opp);
        const details = metadataChips(opp);
        return (
            <motion.article
                key={`${opp.id ?? "row"}-${idx}`}
                initial={{ opacity: 0, scale: 0.98, y: 24 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="card-panel"
                style={{ padding: 0, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
                whileHover={{ y: -5, boxShadow: "var(--shadow-md)", borderColor: "var(--brand-primary)" }}
            >
                <div
                    style={{
                        height: "10px",
                        background:
                            "linear-gradient(90deg, color-mix(in srgb, var(--brand-primary) 88%, white 12%), color-mix(in srgb, var(--brand-accent) 88%, white 12%))",
                        borderBottom: "2px solid var(--border-subtle)",
                    }}
                />
                <div style={{ padding: "1.4rem", display: "flex", flexDirection: "column", gap: "1rem", height: "100%" }}>
                    <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: "1rem" }}>
                        <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.8rem" }}>
                                <span
                                    style={{
                                        fontSize: "0.72rem",
                                        padding: "0.22rem 0.58rem",
                                        borderRadius: "999px",
                                        background: "var(--bg-surface-hover)",
                                        color: "var(--text-primary)",
                                        fontWeight: 900,
                                        textTransform: "uppercase",
                                        border: "2px solid var(--border-subtle)",
                                    }}
                                >
                                    Career Track
                                </span>
                                <span
                                    style={{
                                        fontSize: "0.72rem",
                                        padding: "0.22rem 0.58rem",
                                        borderRadius: "999px",
                                        background: "#ffffff",
                                        color: "#000000",
                                        fontWeight: 900,
                                        textTransform: "uppercase",
                                        border: "2px solid var(--border-subtle)",
                                    }}
                                >
                                    {opp.opportunity_type || "Opportunity"}
                                </span>
                                {renderTrustBadge(opp)}
                            </div>
                            <h2
                                style={{
                                    fontSize: "1.18rem",
                                    marginBottom: "0.45rem",
                                    color: "var(--text-primary)",
                                    lineHeight: 1.25,
                                    fontWeight: 850,
                                }}
                            >
                                {opp.title}
                            </h2>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.88rem" }}>
                                <span style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                    <MapPin size={14} /> {opp.university || "Global"}
                                </span>
                                <span>{formatSourceLabel(opp.source)}</span>
                            </div>
                        </div>
                        <div
                            style={{
                                width: "64px",
                                height: "64px",
                                position: "relative",
                                borderRadius: "16px",
                                overflow: "hidden",
                                flexShrink: 0,
                                border: "2px solid var(--border-subtle)",
                                boxShadow: "var(--shadow-sm)",
                                background: "#111111",
                            }}
                        >
                            <Image
                                src={imageUrl}
                                alt={`${opp.opportunity_type || "Opportunity"} preview`}
                                fill
                                sizes="64px"
                                onError={() => {
                                    if (!imageFallbackMap[opp.id]) {
                                        setImageFallbackMap((prev) => ({ ...prev, [opp.id]: true }));
                                    }
                                }}
                                style={{ objectFit: "cover" }}
                            />
                        </div>
                    </div>

                    <div
                        style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                            gap: "0.8rem",
                            background: "var(--bg-surface-hover)",
                            border: "2px solid var(--border-subtle)",
                            borderRadius: "var(--radius-md)",
                            padding: "0.9rem",
                        }}
                    >
                        <div>
                            <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900, color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                                Domain
                            </div>
                            <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>{opp.domain || "General"}</div>
                        </div>
                        <div>
                            <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900, color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                                Deadline
                            </div>
                            <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>
                                {opp.deadline
                                    ? formatDeadline(opp.deadline, { month: "short", day: "numeric", year: "numeric" })
                                    : "Rolling Basis"}
                            </div>
                        </div>
                    </div>

                    <button
                        type="button"
                        onClick={() => setDetailOpp(opp)}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "0.5rem",
                            width: "100%",
                            marginBottom: "0.25rem",
                            padding: "0.6rem 0.8rem",
                            background: "var(--bg-surface-hover)",
                            border: "2px solid var(--border-subtle)",
                            borderRadius: "var(--radius-md)",
                            fontWeight: 800,
                            fontSize: "0.88rem",
                            color: "var(--text-primary)",
                            cursor: "pointer",
                        }}
                        aria-label={`View full details for ${opp.title}`}
                    >
                        View details
                        <ArrowRight size={15} aria-hidden="true" />
                    </button>
                    <div style={{ display: "grid", gap: "0.18rem" }}>
                        <div style={{ fontSize: "0.8rem", fontWeight: 800, color: "var(--text-primary)" }}>
                            {trust.scoreLabel}
                        </div>
                        <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", fontWeight: 600 }}>
                            {trust.evidenceLabel}
                        </div>
                    </div>
                    {details.length > 0 ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem" }}>
                            {details.map((chip) => (
                                <span
                                    key={chip}
                                    style={{
                                        fontSize: "0.74rem",
                                        padding: "0.22rem 0.55rem",
                                        borderRadius: "999px",
                                        background: "var(--bg-surface-hover)",
                                        border: "1px solid var(--border-subtle)",
                                        fontWeight: 700,
                                        color: "var(--text-secondary)",
                                    }}
                                >
                                    {chip}
                                </span>
                            ))}
                        </div>
                    ) : null}
                    {renderMatchDetails(opp)}

                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "auto" }}>
                        <button
                            className="btn-primary"
                            style={{ padding: "0.7rem 1rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.4rem", border: "2px solid #000000" }}
                            onClick={() => void handleApply(opp)}
                            disabled={applyingId === opp.id}
                        >
                            <Send size={14} />
                            {applyingId === opp.id ? "Applying..." : "Apply"}
                        </button>
                        <button
                            className="btn-secondary"
                            style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                            onClick={() => void handleSave(opp)}
                            disabled={Boolean(savedOpportunityIds[opp.id])}
                        >
                            <Bookmark size={14} />
                            {savedOpportunityIds[opp.id] ? "Saved" : "Save"}
                        </button>
                        <button
                            className="btn-secondary"
                            type="button"
                            style={{ padding: "0.7rem 0.95rem", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: "0.3rem", border: "2px solid var(--border-subtle)" }}
                            onClick={() => handleHide(opp)}
                            aria-label={`Hide ${opp.title}`}
                        >
                            <EyeOff size={14} /> Hide
                        </button>
                    </div>
                </div>
            </motion.article>
        );
    };

    /* Full posting for one opportunity.
       Kept out of the card so the grid stays scannable, and rendered as an
       overlay rather than a route so the reader keeps their scroll position and
       filter state when they close it. Apply here goes to the employer's own
       posting, which is the canonical source and the only place an application
       actually counts. */
    const renderDetailOverlay = () => {
        if (!detailOpp) {
            return null;
        }
        const opp = detailOpp;
        const trust = trustSummary(opp);
        const chips = metadataChips(opp);
        return (
            <div
                role="dialog"
                aria-modal="true"
                aria-label={opp.title}
                onClick={() => setDetailOpp(null)}
                style={{
                    position: "fixed",
                    inset: 0,
                    zIndex: 1000,
                    background: "rgba(0,0,0,0.55)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "1.25rem",
                }}
            >
                <div
                    onClick={(event) => event.stopPropagation()}
                    style={{
                        width: "min(760px, 100%)",
                        maxHeight: "86vh",
                        overflowY: "auto",
                        background: "var(--bg-surface)",
                        border: "2px solid #000000",
                        borderRadius: "var(--radius-lg)",
                        boxShadow: "var(--shadow-lg)",
                        padding: "1.6rem",
                        display: "grid",
                        gap: "1rem",
                    }}
                >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "start" }}>
                        <div>
                            <h2 style={{ fontSize: "1.5rem", fontWeight: 900, color: "var(--text-primary)", marginBottom: "0.4rem" }}>
                                {opp.title}
                            </h2>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", color: "var(--text-secondary)", fontWeight: 700, fontSize: "0.9rem" }}>
                                <span style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                    <MapPin size={14} /> {opp.university || "Global"}
                                </span>
                                <span>{formatSourceLabel(opp.source)}</span>
                            </div>
                        </div>
                        <button
                            type="button"
                            className="btn-secondary"
                            onClick={() => setDetailOpp(null)}
                            aria-label="Close details"
                            style={{ padding: "0.5rem", border: "2px solid var(--border-subtle)", lineHeight: 0 }}
                        >
                            <X size={16} />
                        </button>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.8rem", background: "var(--bg-surface-hover)", border: "2px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "0.9rem" }}>
                        {[
                            ["Domain", opp.domain || "General"],
                            ["Type", opp.opportunity_type || "Opportunity"],
                            ["Deadline", opp.deadline
                                ? formatDeadline(opp.deadline, { month: "short", day: "numeric", year: "numeric" })
                                : "Rolling Basis"],
                        ].map(([label, value]) => (
                            <div key={label}>
                                <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900, color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                                    {label}
                                </div>
                                <div style={{ fontWeight: 800, color: "var(--text-primary)" }}>{value}</div>
                            </div>
                        ))}
                    </div>

                    {isUsableDescription(opp.description) ? (
                        <p style={{ color: "var(--text-secondary)", fontSize: "0.96rem", fontWeight: 500, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                            {opp.description}
                        </p>
                    ) : (
                        <p style={{ color: "var(--text-muted)", fontSize: "0.94rem", fontWeight: 600, lineHeight: 1.6 }}>
                            A full description was not available from this source — see the JD on the job portal.
                        </p>
                    )}

                    {chips.length > 0 ? (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem" }}>
                            {chips.map((chip) => (
                                <span key={chip} style={{ fontSize: "0.76rem", padding: "0.25rem 0.6rem", borderRadius: "999px", background: "var(--bg-surface-hover)", border: "1px solid var(--border-subtle)", fontWeight: 700, color: "var(--text-secondary)" }}>
                                    {chip}
                                </span>
                            ))}
                        </div>
                    ) : null}

                    <div style={{ display: "grid", gap: "0.2rem" }}>
                        <div style={{ fontSize: "0.82rem", fontWeight: 800, color: "var(--text-primary)" }}>{trust.scoreLabel}</div>
                        <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", fontWeight: 600 }}>{trust.evidenceLabel}</div>
                    </div>

                    <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                        <a
                            className="btn-primary"
                            href={opp.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={() => void handleApply(opp)}
                            style={{ padding: "0.75rem 1.1rem", fontSize: "0.92rem", display: "flex", alignItems: "center", gap: "0.4rem", border: "2px solid #000000", textDecoration: "none" }}
                        >
                            <ExternalLink size={15} /> Apply on employer site
                        </a>
                        <button
                            className="btn-secondary"
                            type="button"
                            onClick={() => void handleSave(opp)}
                            disabled={Boolean(savedOpportunityIds[opp.id])}
                            style={{ padding: "0.75rem 1rem", fontSize: "0.92rem", display: "flex", alignItems: "center", gap: "0.35rem", border: "2px solid var(--border-subtle)" }}
                        >
                            <Bookmark size={15} /> {savedOpportunityIds[opp.id] ? "Saved" : "Save"}
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    /* Numbered pager.

       A window of five around the current page rather than all of them: at 12
       per page this corpus is 134 pages, and rendering 134 buttons is its own
       kind of unusable. First/last jumps cover the ends the window cannot
       reach. */
    const renderPager = () => {
        if (pageCount <= 1) {
            return null;
        }
        const windowSize = 5;
        let firstShown = Math.max(1, page - Math.floor(windowSize / 2));
        const lastShown = Math.min(pageCount, firstShown + windowSize - 1);
        // Re-anchor when the window runs past the end, so the last pages still
        // show five buttons instead of trailing off to one.
        firstShown = Math.max(1, lastShown - windowSize + 1);
        const numbers = Array.from({ length: lastShown - firstShown + 1 }, (_, i) => firstShown + i);

        const goTo = (target: number) => {
            const next = Math.max(1, Math.min(pageCount, target));
            if (next !== page) {
                setPage(next);
                // The grid is above the pager; without this the new page lands
                // with the viewport still at the bottom of the previous one.
                window.scrollTo({ top: 0, behavior: "smooth" });
            }
        };

        return (
            <nav className="feed-pager" aria-label="Feed pages">
                <div className="feed-pager-size">
                    <label htmlFor="records-per-page">Records per page:</label>
                    <select
                        id="records-per-page"
                        value={perPage}
                        onChange={(event) => {
                            setPerPage(Number(event.target.value));
                            // Page 7 of 134 is not page 7 of 17. Reset rather
                            // than land the reader somewhere unrelated.
                            setPage(1);
                        }}
                    >
                        {PER_PAGE_OPTIONS.map((option) => (
                            <option key={option} value={option}>{option}</option>
                        ))}
                    </select>
                </div>

                <div className="feed-pager-controls">
                    <button type="button" aria-label="First page" disabled={page === 1} onClick={() => goTo(1)}>|&lt;</button>
                    <button type="button" aria-label="Previous page" disabled={page === 1} onClick={() => goTo(page - 1)}>&lt;</button>
                    {numbers.map((number) => (
                        <button
                            key={number}
                            type="button"
                            aria-label={`Page ${number}`}
                            aria-current={number === page ? "page" : undefined}
                            className={number === page ? "active" : ""}
                            onClick={() => goTo(number)}
                        >
                            {number}
                        </button>
                    ))}
                    <button type="button" aria-label="Next page" disabled={page === pageCount} onClick={() => goTo(page + 1)}>&gt;</button>
                    <button type="button" aria-label="Last page" disabled={page === pageCount} onClick={() => goTo(pageCount)}>&gt;|</button>
                </div>
            </nav>
        );
    };

    const renderSection = (
        title: string,
        subtitle: string,
        items: Opportunity[],
        variant: "competitive" | "career" | "other",
        // Rows matching the filter, which is not the same as rows on screen now.
        // The badge has to keep reporting the former or pagination would look
        // like the filter silently dropped listings.
        totalCount: number = items.length,
    ) => {
        if (!items.length) {
            return null;
        }

        return (
            <section style={{ marginBottom: "3rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
                    <div>
                        <h2 style={{ fontSize: "1.7rem", fontWeight: 900, color: "var(--text-primary)", marginBottom: "0.35rem" }}>
                            {title}
                        </h2>
                        <p style={{ color: "var(--text-secondary)", fontSize: "0.98rem", fontWeight: 600 }}>
                            {subtitle}
                        </p>
                    </div>
                    <div
                        style={{
                            padding: "0.5rem 0.8rem",
                            border: "2px solid var(--border-subtle)",
                            borderRadius: "999px",
                            background: variant === "competitive" ? "var(--brand-accent)" : "var(--bg-surface)",
                            color: "#000000",
                            fontWeight: 900,
                            boxShadow: "var(--shadow-sm)",
                        }}
                    >
                        {totalCount} live
                    </div>
                </div>
                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns:
                            variant === "competitive" ? "1fr" : "repeat(auto-fill, minmax(320px, 1fr))",
                        gap: "1.5rem",
                    }}
                >
                    {/* No AnimatePresence here.
                        It keeps exiting children mounted until their exit
                        animation finishes, and this list is hundreds of cards
                        long: narrowing 797 to 432 left 365 cards animating out
                        while 432 animated in, so the grid held 1227 nodes at
                        once. The count badge sits outside it and updated
                        immediately, which is why the filter looked broken -
                        the number changed and the same cards stayed on screen.
                        Cards still animate in; removal is now instant. */}
                    {items.map((opp, idx) =>
                        variant === "competitive" ? renderCompetitiveCard(opp, idx) : renderCareerCard(opp, idx)
                    )}
                </div>
                {renderPager()}
            </section>
        );
    };

    return (
        <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--bg-base)', position: 'relative' }}>

            <Sidebar />
            <main className="main-content">
                <header style={{ marginBottom: '3rem' }}>
                    <h1 style={{ fontSize: '3rem', marginBottom: '0.75rem', fontWeight: 400, fontFamily: 'var(--font-serif)', color: 'var(--text-primary)', lineHeight: 1.1 }}>
                        Discover <span style={{ background: 'var(--brand-accent)', padding: '0.2rem 0.5rem', border: '2px solid var(--border-subtle)', boxShadow: 'var(--shadow-sm)', display: 'inline-block', transform: 'rotate(-2deg)' }}>Internships/Jobs</span>
                    </h1>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '1.25rem', maxWidth: '600px', fontWeight: 600 }}>
                        Track internship and job openings from top universities, startups, and global companies.
                    </p>
                </header>

                {/* Brutalist Navigation Filters */}

                {/* The only top-level filter on this page. The old domain
                    chip row was removed: it was auto-derived from scraped data,
                    so it surfaced values like "cloudflare.com" as a filter, and
                    it sat above these tabs competing for the same attention. */}
                <div className="role-track-tabs" role="tablist" aria-label="Role track">
                    {([
                        { key: "all" as const, label: "All roles" },
                        { key: "technical" as const, label: "Technical" },
                        { key: "non_technical" as const, label: "Non-technical" },
                    ]).map((tab) => (
                        <button
                            key={tab.key}
                            type="button"
                            role="tab"
                            aria-selected={roleTrack === tab.key}
                            className={`role-track-tab ${roleTrack === tab.key ? "active" : ""}`}
                            onClick={() => {
                                setRoleTrack(tab.key);
                                // Selections from the other track would match nothing.
                                setTrackKeywords([]);
                                setFilterMenuOpen(false);
                            }}
                        >
                            {tab.label}
                            <span className="role-track-count">{trackCounts[tab.key]}</span>
                        </button>
                    ))}
                </div>

                {/* Filter bar. The placement and speciality filters are both
                    dropdowns now. As pill rows they were 5 and 17 controls
                    stacked under the three role tabs - 25 competing targets
                    before a single listing was visible, which pushed the feed
                    off the first screen and read as clutter rather than choice.

                    Counts move onto the options inside each menu, where they
                    still answer "how many would this give me" at the moment the
                    student is choosing, without spending header width. */}
                <div className="feed-filter-bar">
                    <div className="track-filter-select">
                        <button
                            type="button"
                            className="track-filter-trigger"
                            aria-expanded={placementMenuOpen}
                            aria-haspopup="listbox"
                            onClick={() => {
                                setPlacementMenuOpen((open) => !open);
                                setFilterMenuOpen(false);
                            }}
                        >
                            <span>
                                {placement === "all"
                                    ? "Location & work mode"
                                    : PLACEMENT_TABS.find((tab) => tab.key === placement)?.label}
                            </span>
                            <ChevronDown size={16} aria-hidden="true" />
                        </button>

                        {placement !== "all" && (
                            <button
                                type="button"
                                className="track-filter-clear"
                                onClick={() => setPlacement("all")}
                            >
                                Clear
                            </button>
                        )}

                        {placementMenuOpen && (
                            <>
                                <button
                                    type="button"
                                    className="track-filter-backdrop"
                                    aria-label="Close location filter"
                                    onClick={() => setPlacementMenuOpen(false)}
                                />
                                <div className="track-filter-menu" role="listbox">
                                    {PLACEMENT_TABS.map((tab) => (
                                        <label key={tab.key} className="track-filter-option">
                                            <input
                                                type="radio"
                                                name="placement"
                                                checked={placement === tab.key}
                                                onChange={() => {
                                                    setPlacement(tab.key);
                                                    setPlacementMenuOpen(false);
                                                }}
                                            />
                                            <span>{tab.label}</span>
                                            <span className="track-filter-count">
                                                {placementCounts[tab.key]}
                                            </span>
                                        </label>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>

                {/* Speciality filter. A dropdown rather than another chip row:
                    a second row of pills read as a peer of the track tabs and
                    was easy to mistake for one. Multi-select, because a student
                    is rarely interested in exactly one speciality. */}
                {trackFilters.length > 0 && (
                    <div className="track-filter-select">
                        <button
                            type="button"
                            className="track-filter-trigger"
                            aria-expanded={filterMenuOpen}
                            aria-haspopup="listbox"
                            onClick={() => setFilterMenuOpen((open) => !open)}
                        >
                            <span>
                                {trackKeywords.length === 0
                                    ? "Filter by speciality"
                                    : `${trackKeywords.length} speciality${trackKeywords.length > 1 ? "s" : ""} selected`}
                            </span>
                            <ChevronDown size={16} aria-hidden="true" />
                        </button>

                        {trackKeywords.length > 0 && (
                            <button
                                type="button"
                                className="track-filter-clear"
                                onClick={() => setTrackKeywords([])}
                            >
                                Clear
                            </button>
                        )}

                        {filterMenuOpen && (
                            <>
                                {/* Click-away target, so the menu closes without
                                    a document-level listener. */}
                                <button
                                    type="button"
                                    className="track-filter-backdrop"
                                    aria-label="Close speciality filter"
                                    onClick={() => setFilterMenuOpen(false)}
                                />
                                <div className="track-filter-menu" role="listbox" aria-multiselectable="true">
                                    {trackFilters.map((filter) => {
                                        const checked = trackKeywords.includes(filter.label);
                                        return (
                                            <label key={filter.label} className="track-filter-option">
                                                <input
                                                    type="checkbox"
                                                    checked={checked}
                                                    onChange={() =>
                                                        setTrackKeywords((current) =>
                                                            current.includes(filter.label)
                                                                ? current.filter((item) => item !== filter.label)
                                                                : [...current, filter.label],
                                                        )
                                                    }
                                                />
                                                <span>{filter.label}</span>
                                            </label>
                                        );
                                    })}
                                </div>
                            </>
                        )}
                    </div>
                )}
                </div>

                <AskAIPanel
                    surface="internships_jobs_page"
                    suggestedQueries={[
                        "remote internships for data science and analytics with citations",
                        "software internships that fit React and TypeScript skills",
                        "entry-level AI roles with strong ranking evidence and recent activity",
                    ]}
                />

                {/* Interactive Grid Layout */}
                {notice && (
                    <div className="card-panel" style={{ marginBottom: "1.5rem", background: "var(--bg-surface-hover)" }}>
                        <strong>{notice}</strong>
                    </div>
                )}
                {loading ? (
                    <OpportunityCardsSkeleton count={6} />
                ) : (
                    <>
                        {/* visibleOpportunities, not grouped.career: the track and
                            speciality selections are applied there. Rendering the
                            unfiltered group made every chip look inert - the
                            highlight moved but the same cards stayed on screen. */}
                        {renderSection(
                            "Jobs & Internships",
                            "Hiring-focused roles, internships, and career-track openings.",
                            visibleOpportunities,
                            "career",
                            // Rows matching the filter, not rows on this page.
                            totalCount,
                        )}
                        {!visibleOpportunities.length && (
                            <div className="card-panel" style={{ padding: "1.5rem" }}>
                                <strong>
                                    {trackKeywords.length > 0
                                        ? `No ${trackKeywords.join(", ")} roles right now.`
                                        : roleTrack === "all"
                                          ? "No internships or jobs match this filter right now."
                                          : `No ${roleTrack === "technical" ? "technical" : "non-technical"} roles match this filter right now.`}
                                </strong>
                                {/* Name the placement pill explicitly. Otherwise a
                                    student who picked Hybrid sees a generic empty
                                    state and concludes the page is broken rather
                                    than that this one filter is narrow. */}
                                {placement !== "all" && (
                                    <p style={{ marginTop: "0.5rem" }}>
                                        The{" "}
                                        <strong>
                                            {PLACEMENT_TABS.find((tab) => tab.key === placement)?.label}
                                        </strong>{" "}
                                        filter is applied.{" "}
                                        <button
                                            type="button"
                                            className="placement-tab"
                                            onClick={() => setPlacement("all")}
                                        >
                                            Show all locations
                                        </button>
                                    </p>
                                )}
                            </div>
                        )}
                    </>
                )}
            </main>
            {renderDetailOverlay()}
        </div>
    );
}
