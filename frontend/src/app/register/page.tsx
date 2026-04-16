"use client";
import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { apiUrl } from '@/lib/api';
import BrandLogo from '@/components/BrandLogo';

export default function RegisterPage() {
    const router = useRouter();
    const [fullName, setFullName] = useState('');
    const [email, setEmail] = useState('');
    const [otp, setOtp] = useState('');
    const [step, setStep] = useState(1); // 1 = Details, 2 = OTP
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [info, setInfo] = useState<string | null>(null);

    const handleSendOTP = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError(null);
        setInfo(null);

        try {
            const res = await fetch(apiUrl('/api/v1/auth/send-otp'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, purpose: "signup" })
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Failed to send OTP");
            }

            if (typeof data.debug_otp === 'string' && data.debug_otp.length === 6) {
                setOtp(data.debug_otp);
                setInfo(`SMTP unavailable in local mode. Use OTP: ${data.debug_otp} (expires in 5 minutes).`);
            } else {
                setOtp('');
                setInfo("OTP sent to your email. It expires in 5 minutes.");
            }
            setStep(2);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    };

    const handleVerifyRegistration = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const res = await fetch(apiUrl('/api/v1/auth/verify-otp'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, otp, full_name: fullName, purpose: "signup" })
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || "Invalid OTP");
            }

            const data = await res.json();
            localStorage.setItem("access_token", data.access_token);
            router.push('/dashboard');
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{ minHeight: '100vh', display: 'flex', background: 'var(--bg-base)' }}>

            {/* Visual Pane (Left) */}
            <div className="hidden lg:flex" style={{
                flex: 1,
                background: 'linear-gradient(135deg, var(--brand-primary), var(--accent-cyan))',
                position: 'relative',
                overflow: 'hidden',
                flexDirection: 'column',
                justifyContent: 'space-between',
                padding: '4rem'
            }}>
                {/* Decorative circles */}
                <div style={{ position: 'absolute', top: '10%', left: '-10%', width: '500px', height: '500px', borderRadius: '50%', background: 'rgba(255,255,255,0.1)', filter: 'blur(40px)' }} />
                <div style={{ position: 'absolute', bottom: '-10%', right: '-10%', width: '400px', height: '400px', borderRadius: '50%', background: 'rgba(59, 130, 246, 0.3)', filter: 'blur(60px)' }} />

                <div style={{ position: 'relative', zIndex: 10 }}>
                    <BrandLogo size="md" />
                </div>

                <div style={{ position: 'relative', zIndex: 10, maxWidth: '500px' }}>
                    <h2 style={{ fontSize: '3.5rem', color: '#ffffff', marginBottom: '1rem', lineHeight: 1.1, fontWeight: 800 }}>
                        Unlock Your Potential.
                    </h2>
                    <p style={{ color: 'rgba(255,255,255,0.85)', fontSize: '1.25rem', lineHeight: 1.5 }}>
                        Join the world&apos;s fastest-growing academic intelligence network. Track opportunities, network with peers, and build an unstoppable profile.
                    </p>
                </div>
            </div>

            {/* Form Pane (Right) */}
            <div style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '2rem'
            }}>
                <div className="animate-fade-up" style={{ width: '100%', maxWidth: '440px' }}>
                    <div style={{ textAlign: 'left', marginBottom: '2.5rem' }}>
                        <div className="block lg:hidden" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '2rem' }}>
                            <BrandLogo size="md" />
                        </div>

                        <h1 style={{ fontSize: '2rem', marginBottom: '0.75rem', letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>Apply for Access</h1>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '1rem' }}>
                            {step === 1 ? "Provide your details to securely create an account." : "Enter the 6-digit code sent to your email to verify ownership."}
                        </p>
                    </div>

                    {error && (
                        <div style={{ padding: '1rem', background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', borderRadius: 'var(--radius-sm)', marginBottom: '1.5rem', fontSize: '0.9rem', fontWeight: 500 }}>
                            {error}
                        </div>
                    )}
                    {info && (
                        <div style={{ padding: '1rem', background: 'rgba(34, 197, 94, 0.12)', color: '#22c55e', borderRadius: 'var(--radius-sm)', marginBottom: '1.5rem', fontSize: '0.9rem', fontWeight: 600 }}>
                            {info}
                        </div>
                    )}

                    <div className="card-panel" style={{ padding: '2.5rem', boxShadow: 'var(--shadow-lg)' }}>
                        {step === 1 ? (
                            <form onSubmit={handleSendOTP} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-primary)', fontWeight: 600 }}>Full Name</label>
                                    <input
                                        type="text"
                                        className="input-base"
                                        placeholder="E.g., Jane Doe"
                                        value={fullName}
                                        onChange={(e) => setFullName(e.target.value)}
                                        required
                                        disabled={loading}
                                    />
                                </div>
                                <div>
                                    <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-primary)', fontWeight: 600 }}>Email Address</label>
                                    <input
                                        type="email"
                                        className="input-base"
                                        placeholder="student@university.edu"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        required
                                        disabled={loading}
                                    />
                                </div>

                                <button type="submit" className="btn-primary" style={{ width: '100%', padding: '1rem', marginTop: '0.5rem' }} disabled={loading}>
                                    {loading ? "Sending Code..." : "Send Verification Code"}
                                </button>
                            </form>
                        ) : (
                            <form onSubmit={handleVerifyRegistration} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-primary)', fontWeight: 600 }}>Verification Code</label>
                                    <input
                                        type="text"
                                        className="input-base"
                                        placeholder="123456"
                                        value={otp}
                                        onChange={(e) => setOtp(e.target.value)}
                                        minLength={6}
                                        maxLength={6}
                                        required
                                        disabled={loading}
                                        style={{ textAlign: "center", letterSpacing: "8px", fontSize: "1.5rem", fontWeight: 700 }}
                                    />
                                </div>

                                <button type="submit" className="btn-primary" style={{ width: '100%', padding: '1rem' }} disabled={loading}>
                                    {loading ? "Verifying..." : "Verify & Complete Signup"}
                                </button>

                                <div style={{ textAlign: 'center', marginTop: '0.5rem' }}>
                                    <button type="button" onClick={() => setStep(1)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 500, textDecoration: 'underline' }}>
                                        Go back
                                    </button>
                                </div>
                            </form>
                        )}
                    </div>

                    {step === 1 && (
                        <div style={{ marginTop: '2.5rem', textAlign: 'center', fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
                            Already hold an account? <Link href="/login" style={{ color: 'var(--brand-primary)', fontWeight: 600 }}>Sign in</Link>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
