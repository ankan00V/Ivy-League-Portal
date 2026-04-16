"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '@/context/ThemeContext';
import { LayoutDashboard, Target, Briefcase, FileText, Globe, Trophy, Sun, Moon, BarChart3 } from 'lucide-react';
import { useSyncExternalStore } from 'react';
import BrandLogo from '@/components/BrandLogo';

export default function Sidebar() {
    const pathname = usePathname();
    const { theme, toggleTheme } = useTheme();
    const isHydrated = useSyncExternalStore(
        () => () => { },
        () => true,
        () => false
    );

    const links = [
        { name: 'Dashboard', href: '/dashboard', icon: <LayoutDashboard size={20} /> },
        { name: 'Opportunities', href: '/opportunities', icon: <Target size={20} /> },
        { name: 'Internships/Jobs', href: '/internships-jobs', icon: <Briefcase size={20} /> },
        { name: 'Applications', href: '/applications', icon: <FileText size={20} /> },
        { name: 'Social Network', href: '/social', icon: <Globe size={20} /> },
        { name: 'Leaderboard', href: '/leaderboard', icon: <Trophy size={20} /> },
        { name: 'Experiments', href: '/experiments', icon: <BarChart3 size={20} /> },
    ];

    return (
        <div
            style={{
                width: 'var(--sidebar-width)',
                flexShrink: 0,
                alignSelf: 'stretch',
                position: 'relative',
            }}
        >
        <aside style={{
            width: '100%',
            background: 'var(--bg-sidebar)',
            height: '100vh',
            minHeight: '100vh',
            position: 'sticky',
            top: 0,
            display: 'flex',
            flexDirection: 'column',
            padding: '2.5rem 1.5rem max(1.25rem, env(safe-area-inset-bottom)) 1.5rem',
            zIndex: 40,
            transition: 'var(--standard-transition)',
            overflow: 'hidden'
        }}>
            <div style={{ marginBottom: '2.5rem', paddingLeft: '0.2rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <BrandLogo size="lg" />
            </div>

            <nav style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '0.75rem',
                flex: 1,
                minHeight: 0,
                overflowY: 'auto',
                paddingTop: '0.35rem',
                paddingBottom: '0.35rem',
                paddingRight: '0.25rem',
                position: 'relative'
            }}>
                {links.map((link) => {
                    const isActive = pathname === link.href;
                    return (
                        <Link
                            key={link.name}
                            href={link.href}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '1rem',
                                padding: '1rem 1.25rem',
                                color: isActive ? '#000000' : 'var(--text-primary)',
                                fontWeight: 600,
                                background: isActive ? 'var(--brand-primary)' : 'transparent',
                                border: isActive ? '2px solid var(--border-subtle)' : '2px solid transparent',
                                boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                                transition: 'var(--standard-transition)',
                                borderRadius: 'var(--radius-sm)',
                                transform: 'none'
                            }}
                            onMouseEnter={(e) => {
                                if (!isActive) {
                                    e.currentTarget.style.background = 'var(--bg-surface-hover)';
                                    e.currentTarget.style.border = '2px solid var(--border-subtle)';
                                    e.currentTarget.style.boxShadow = 'var(--shadow-sm)';
                                    e.currentTarget.style.transform = 'translateY(-1px)';
                                }
                            }}
                            onMouseLeave={(e) => {
                                if (!isActive) {
                                    e.currentTarget.style.background = 'transparent';
                                    e.currentTarget.style.border = '2px solid transparent';
                                    e.currentTarget.style.boxShadow = 'none';
                                    e.currentTarget.style.transform = 'none';
                                }
                            }}
                        >
                            <span style={{ display: 'flex', alignItems: 'center' }}>{link.icon}</span>
                            <span>{link.name}</span>
                        </Link>
                    );
                })}
            </nav>

            <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', paddingTop: '1rem', flexShrink: 0 }}>
                {/* Theme Toggle Button */}
                <button
                    onClick={toggleTheme}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '0.75rem',
                        padding: '1rem',
                        background: 'var(--bg-surface)',
                        border: '2px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                        fontWeight: 600,
                        cursor: 'pointer',
                        boxShadow: 'var(--shadow-sm)',
                        transition: 'var(--standard-transition)',
                        width: '100%'
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'translateY(-2px)';
                        e.currentTarget.style.boxShadow = 'var(--shadow-md)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'none';
                        e.currentTarget.style.boxShadow = 'var(--shadow-sm)';
                    }}
                    onMouseDown={(e) => {
                        e.currentTarget.style.transform = 'translateY(2px)';
                        e.currentTarget.style.boxShadow = 'none';
                    }}
                    onMouseUp={(e) => {
                        e.currentTarget.style.transform = 'translateY(-2px)';
                        e.currentTarget.style.boxShadow = 'var(--shadow-md)';
                    }}
                >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.75rem' }}>
                        {!isHydrated ? (
                            <><Sun size={20} /> Theme</>
                        ) : theme === 'dark' ? (
                            <><Sun size={20} /> Light Mode</>
                        ) : (
                            <><Moon size={20} /> Dark Mode</>
                        )}
                    </span>
                </button>

                {/* Global Rank Snippet */}
                <div style={{
                    padding: '1.25rem',
                    background: 'var(--brand-accent)',
                    borderRadius: 'var(--radius-sm)',
                    border: '2px solid var(--border-subtle)',
                    boxShadow: 'var(--shadow-sm)',
                    textAlign: 'center',
                    color: '#000000',
                    transition: 'var(--standard-transition)',
                    width: '100%'
                }}>
                    <div style={{ fontSize: '0.875rem', marginBottom: '0.25rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Global Rank</div>
                    <div style={{ fontSize: '2rem', fontWeight: 400, fontFamily: 'var(--font-serif)', lineHeight: 1, margin: '0.5rem 0' }}>Top 5%</div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>Keep applying!</div>
                </div>
            </div>

        </aside>
        <div
            aria-hidden
            style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                right: '-5px',
                width: '2px',
                background: 'var(--border-subtle)',
                pointerEvents: 'none',
                zIndex: 45,
            }}
        />
        </div>
    );
}
