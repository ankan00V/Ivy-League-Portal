"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '@/context/ThemeContext';
import { LayoutDashboard, Target, FileText, Globe, Trophy, Sun, Moon, BarChart3 } from 'lucide-react';
import { useSyncExternalStore } from 'react';

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
        { name: 'Applications', href: '/applications', icon: <FileText size={20} /> },
        { name: 'Social Network', href: '/social', icon: <Globe size={20} /> },
        { name: 'Leaderboard', href: '/leaderboard', icon: <Trophy size={20} /> },
        { name: 'Experiments', href: '/experiments', icon: <BarChart3 size={20} /> },
    ];

    return (
        <aside style={{
            width: 'var(--sidebar-width)',
            background: 'var(--bg-sidebar)',
            borderRight: '2px solid var(--border-subtle)',
            height: '100vh',
            position: 'sticky',
            top: 0,
            display: 'flex',
            flexDirection: 'column',
            padding: '2.5rem 1.5rem',
            zIndex: 40,
            transition: 'var(--standard-transition)'
        }}>
            <div style={{ marginBottom: '3.5rem', paddingLeft: '0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Link href="/" style={{ fontSize: '2.5rem', fontWeight: 400, fontFamily: 'var(--font-serif)', letterSpacing: '-0.02em', color: 'var(--text-primary)', lineHeight: 1 }}>
                    VidyaVerse
                </Link>
            </div>

            <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', flex: 1, position: 'relative' }}>
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
                                transform: isActive ? 'translateY(-2px)' : 'none'
                            }}
                            onMouseEnter={(e) => {
                                if (!isActive) {
                                    e.currentTarget.style.background = 'var(--bg-surface-hover)';
                                    e.currentTarget.style.border = '2px solid var(--border-subtle)';
                                    e.currentTarget.style.boxShadow = 'var(--shadow-sm)';
                                    e.currentTarget.style.transform = 'translateY(-2px)';
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

            <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
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
                        transition: 'var(--standard-transition)'
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
                    transition: 'var(--standard-transition)'
                }}>
                    <div style={{ fontSize: '0.875rem', marginBottom: '0.25rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Global Rank</div>
                    <div style={{ fontSize: '2rem', fontWeight: 400, fontFamily: 'var(--font-serif)', lineHeight: 1, margin: '0.5rem 0' }}>Top 5%</div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>Keep applying!</div>
                </div>
            </div>
        </aside>
    );
}
