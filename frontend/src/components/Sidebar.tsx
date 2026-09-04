"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  Briefcase,
  FileText,
  Globe,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Sun,
  Target,
  Trophy,
  X,
  Compass,
  GraduationCap,
  Building2,
} from "lucide-react";

import BrandLogo from "@/components/BrandLogo";
import { useTheme } from "@/context/ThemeContext";
import { apiUrl } from "@/lib/api";
import { clearAccessToken, createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { formatTopPercent, type RankingSummary } from "@/lib/ranking-summary";

type NavLink = {
  name: string;
  href: string;
  icon: React.ReactNode;
  /** Roles that should see this link. Empty means everyone. */
  roles?: string[];
  mobileLabel?: string;
};

// Links carry the roles that should see them. An academician handed the student
// feed, or a student shown a cohort dashboard they cannot open, are both
// navigation that only leads to a refusal.
const STUDENT_ONLY = ["candidate"];
const EVERY_ROLE: string[] = [];

const links: NavLink[] = [
  { name: "Dashboard", href: "/dashboard", icon: <LayoutDashboard size={18} />, mobileLabel: "Home", roles: EVERY_ROLE },
  { name: "Opportunities", href: "/opportunities", icon: <Target size={18} />, mobileLabel: "Opps", roles: STUDENT_ONLY },
  { name: "Internships/Jobs", href: "/internships-jobs", icon: <Briefcase size={18} />, mobileLabel: "Jobs", roles: STUDENT_ONLY },
  { name: "Applications", href: "/applications", icon: <FileText size={18} />, mobileLabel: "Applied", roles: STUDENT_ONLY },
  { name: "Skill Gaps", href: "/skills", icon: <Compass size={18} />, mobileLabel: "Skills", roles: STUDENT_ONLY },
  { name: "Faculty Portal", href: "/faculty", icon: <GraduationCap size={18} />, mobileLabel: "Faculty", roles: ["faculty"] },
  { name: "Cohort", href: "/institution", icon: <Building2 size={18} />, mobileLabel: "Cohort", roles: ["institution"] },
  { name: "Social Network", href: "/social", icon: <Globe size={18} />, mobileLabel: "Social", roles: EVERY_ROLE },
  { name: "Leaderboard", href: "/leaderboard", icon: <Trophy size={18} />, roles: STUDENT_ONLY },
];

// Intentionally NOT computed here.
//
// This was `links.slice(0, 5)` - the full list, before role filtering - so the
// mobile bottom bar offered Dashboard, Opportunities, Internships/Jobs,
// Applications and Skill Gaps to every account including faculty and
// institution. Those routes do not 403; they serve the student feed to an
// academician, which is the same mis-scoping as the leaderboard bug. It is
// derived from visibleLinks inside the component instead, where the role is
// known.

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const [rankingSummary, setRankingSummary] = useState<RankingSummary | null>(null);
  const [accountType, setAccountType] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isHydrated = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  useEffect(() => {
    let cancelled = false;

    // Which links to show depends on the role. Until it is known the student
    // navigation is shown, which is right for the overwhelming majority and
    // wrong only briefly for the rest.
    const loadAccountType = async () => {
      const token = getAccessToken();
      if (!token) return;
      try {
        const res = await fetch(
          apiUrl("/api/v1/users/me/profile"),
          createAuthenticatedFetchInit({}, token),
        );
        if (!res.ok) return;
        const payload = (await res.json()) as { account_type?: string | null };
        if (!cancelled) {
          setAccountType(String(payload?.account_type ?? "candidate").trim().toLowerCase());
        }
      } catch {
        // A role we cannot read leaves the shared links only, which every
        // account can open.
      }
    };
    void loadAccountType();

    const loadRankingSummary = async () => {
      const token = getAccessToken();
      if (!token) {
        if (!cancelled) {
          setRankingSummary(null);
        }
        return;
      }
      try {
        const res = await fetch(
          apiUrl("/api/v1/users/me/ranking-summary"),
          createAuthenticatedFetchInit({}, token),
        );
        if (!res.ok) {
          if (!cancelled) {
            setRankingSummary(null);
          }
          return;
        }
        const payload: RankingSummary = await res.json();
        if (!cancelled) {
          setRankingSummary(payload);
        }
      } catch {
        if (!cancelled) {
          setRankingSummary(null);
        }
      }
    };

    void loadRankingSummary();
    const interval = window.setInterval(() => {
      void loadRankingSummary();
    }, 30000);
    const handleRefresh = () => {
      void loadRankingSummary();
    };

    window.addEventListener("focus", handleRefresh);
    document.addEventListener("visibilitychange", handleRefresh);

  return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", handleRefresh);
      document.removeEventListener("visibilitychange", handleRefresh);
    };
  }, []);

  useEffect(() => {
    if (!drawerOpen) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen]);

  const globalRankTitle = rankingSummary
    ? rankingSummary.top_percent != null
      ? `Top ${formatTopPercent(rankingSummary.top_percent)}%`
      : rankingSummary.band || "--"
    : "--";
  // The backend already withholds the percentile below MIN_COHORT_FOR_PERCENTILE
  // because a percentile over a handful of people is noise. Printing the raw
  // "#N of M" underneath handed the reader the same noise with a smaller
  // denominator - with the demo accounts it read "Rank #1 of 3".
  const globalRankSubtitle = rankingSummary
    ? rankingSummary.cohort_ready
      ? `Rank #${rankingSummary.rank} of ${rankingSummary.total_users}`
      : "Cohort too small to rank yet"
    : "Live rank unavailable";

  const themeLabel = useMemo(() => {
    if (!isHydrated) {
      return "Theme";
    }
    return theme === "dark" ? "Light Mode" : "Dark Mode";
  }, [isHydrated, theme]);

  const handleLogout = () => {
    clearAccessToken();
    setDrawerOpen(false);
    router.replace("/login");
  };

  // Which links this account should see. Roles are checked here rather than by
  // hiding pages, so navigation never offers a route that answers 403.
  //
  // An unknown role falls back to the student navigation rather than to nothing.
  // The role is read from an authenticated request, so it is null for a signed
  // out or expired session and for any hiccup on that one endpoint - and the
  // first version of this stripped the sidebar down to two links whenever that
  // happened. A faculty member seeing a student link for a moment is a much
  // smaller failure than every user losing their navigation.
  const effectiveRole = accountType || "candidate";
  const visibleLinks = links.filter((link) => {
    if (!link.roles || link.roles.length === 0) return true;
    return link.roles.includes(effectiveRole);
  });
  // The mobile bar is the first five links this role can actually open.
  const mobilePrimaryLinks = visibleLinks.slice(0, 5);

  return (
    <>
      <div className="app-shell-nav-root">
        <aside className="desktop-sidebar">
          <div className="sidebar-top">
            <BrandLogo size="lg" />
          </div>

          <nav className="sidebar-links" aria-label="Primary">
            {visibleLinks.map((link) => {
              const isActive = pathname === link.href;
              return (
                <Link
                  key={link.name}
                  href={link.href}
                  className={`sidebar-link ${isActive ? "active" : ""}`}
                  onClick={() => setDrawerOpen(false)}
                >
                  <span className="sidebar-link-icon">{link.icon}</span>
                  <span>{link.name}</span>
                </Link>
              );
            })}
          </nav>

          <div className="sidebar-foot">
            <button type="button" onClick={toggleTheme} className="sidebar-theme-btn">
              <span className="sidebar-link-icon">{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}</span>
              <span>{themeLabel}</span>
            </button>
            <div className="sidebar-rank-card">
              <div className="sidebar-rank-title">Your cohort</div>
              <div className="sidebar-rank-value">{globalRankTitle}</div>
              <div className="sidebar-rank-detail">{globalRankSubtitle}</div>
            </div>
            <button type="button" onClick={handleLogout} className="sidebar-logout-btn">
              <span className="sidebar-link-icon">
                <LogOut size={18} />
              </span>
              <span>Logout</span>
            </button>
          </div>
        </aside>
      </div>

      <header className="mobile-topbar">
        <BrandLogo size="sm" />
        <div style={{ display: "flex", gap: "0.45rem", alignItems: "center" }}>
          <button type="button" className="mobile-icon-btn" onClick={toggleTheme} aria-label={themeLabel}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            type="button"
            className="mobile-icon-btn"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation menu"
            aria-expanded={drawerOpen}
          >
            <Menu size={18} />
          </button>
        </div>
      </header>

      <div className={`mobile-drawer-backdrop ${drawerOpen ? "open" : ""}`} onClick={() => setDrawerOpen(false)} />
      <aside className={`mobile-drawer ${drawerOpen ? "open" : ""}`} aria-hidden={!drawerOpen}>
        <div className="mobile-drawer-head">
          <BrandLogo size="sm" />
          <button
            type="button"
            className="mobile-icon-btn"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation menu"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="mobile-drawer-links" aria-label="Mobile navigation">
          {visibleLinks.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.name}
                href={link.href}
                className={`mobile-drawer-link ${isActive ? "active" : ""}`}
                onClick={() => setDrawerOpen(false)}
              >
                <span className="sidebar-link-icon">{link.icon}</span>
                <span>{link.name}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mobile-drawer-foot">
          <div className="sidebar-rank-card">
            <div className="sidebar-rank-title">Your cohort</div>
            <div className="sidebar-rank-value">{globalRankTitle}</div>
            <div className="sidebar-rank-detail">{globalRankSubtitle}</div>
          </div>
          <button type="button" onClick={handleLogout} className="sidebar-logout-btn">
            <span className="sidebar-link-icon">
              <LogOut size={18} />
            </span>
            <span>Logout</span>
          </button>
        </div>
      </aside>

      <nav className="mobile-bottom-nav" aria-label="Primary mobile routes">
        {mobilePrimaryLinks.map((link) => {
          const isActive = pathname === link.href;
          return (
            <Link key={link.name} href={link.href} className={`mobile-bottom-item ${isActive ? "active" : ""}`}>
              <span className="sidebar-link-icon">{link.icon}</span>
              <span>{link.mobileLabel || link.name}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
