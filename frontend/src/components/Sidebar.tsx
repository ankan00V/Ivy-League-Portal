"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  BarChart3,
  Briefcase,
  FileText,
  Globe,
  LayoutDashboard,
  Menu,
  Moon,
  Sun,
  Target,
  Trophy,
  X,
} from "lucide-react";

import BrandLogo from "@/components/BrandLogo";
import { useTheme } from "@/context/ThemeContext";
import { apiUrl } from "@/lib/api";
import { createAuthenticatedFetchInit, getAccessToken } from "@/lib/auth-session";
import { formatTopPercent, type RankingSummary } from "@/lib/ranking-summary";

type NavLink = {
  name: string;
  href: string;
  icon: React.ReactNode;
  mobileLabel?: string;
};

const links: NavLink[] = [
  { name: "Dashboard", href: "/dashboard", icon: <LayoutDashboard size={18} />, mobileLabel: "Home" },
  { name: "Opportunities", href: "/opportunities", icon: <Target size={18} />, mobileLabel: "Opps" },
  { name: "Internships/Jobs", href: "/internships-jobs", icon: <Briefcase size={18} />, mobileLabel: "Jobs" },
  { name: "Applications", href: "/applications", icon: <FileText size={18} />, mobileLabel: "Applied" },
  { name: "Social Network", href: "/social", icon: <Globe size={18} />, mobileLabel: "Social" },
  { name: "Leaderboard", href: "/leaderboard", icon: <Trophy size={18} /> },
  { name: "Experiments", href: "/experiments", icon: <BarChart3 size={18} /> },
];

const mobilePrimaryLinks = links.slice(0, 5);

export default function Sidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const [rankingSummary, setRankingSummary] = useState<RankingSummary | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isHydrated = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  useEffect(() => {
    let cancelled = false;

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

  const globalRankTitle = rankingSummary ? `Top ${formatTopPercent(rankingSummary.top_percent)}%` : "--";
  const globalRankSubtitle = rankingSummary
    ? `Rank #${rankingSummary.rank} of ${rankingSummary.total_users}`
    : "Live rank unavailable";

  const themeLabel = useMemo(() => {
    if (!isHydrated) {
      return "Theme";
    }
    return theme === "dark" ? "Light Mode" : "Dark Mode";
  }, [isHydrated, theme]);

  return (
    <>
      <div className="app-shell-nav-root" aria-hidden>
        <aside className="desktop-sidebar">
          <div className="sidebar-top">
            <BrandLogo size="lg" />
          </div>

          <nav className="sidebar-links" aria-label="Primary">
            {links.map((link) => {
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
              <div className="sidebar-rank-title">Global Rank</div>
              <div className="sidebar-rank-value">{globalRankTitle}</div>
              <div className="sidebar-rank-detail">{globalRankSubtitle}</div>
            </div>
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
          {links.map((link) => {
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
            <div className="sidebar-rank-title">Global Rank</div>
            <div className="sidebar-rank-value">{globalRankTitle}</div>
            <div className="sidebar-rank-detail">{globalRankSubtitle}</div>
          </div>
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
