import type { Metadata } from "next";
import { Space_Grotesk, Instrument_Serif } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { ThemeProvider } from "@/context/ThemeContext";
import VidyaChat from "@/components/VidyaChat";
import SessionManager from "@/components/SessionManager";
import ThemeToggleButton from "@/components/ThemeToggleButton";
import { ACCESS_TOKEN_EXPIRES_AT_KEY, ACCESS_TOKEN_KEY } from "@/lib/auth-session";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: '--font-sans',
  weight: ["300", "400", "500", "600", "700"],
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: '--font-serif',
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "VidyaVerse - Ivy League Opportunity Intelligence",
  description: "Real-Time Academic Intelligence Network powered by AI to connect students with elite opportunities.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const bootstrapAuthCleanupScript = `
    (() => {
      try {
        const token = window.localStorage.getItem(${JSON.stringify(ACCESS_TOKEN_KEY)});
        const rawExpiry = window.localStorage.getItem(${JSON.stringify(ACCESS_TOKEN_EXPIRES_AT_KEY)});
        const expiresAt = Number(rawExpiry);
        if (!token) {
          window.localStorage.removeItem(${JSON.stringify(ACCESS_TOKEN_EXPIRES_AT_KEY)});
          return;
        }
        if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
          window.localStorage.removeItem(${JSON.stringify(ACCESS_TOKEN_KEY)});
          window.localStorage.removeItem(${JSON.stringify(ACCESS_TOKEN_EXPIRES_AT_KEY)});
        }
      } catch {
        // Ignore storage access issues during bootstrap.
      }
    })();
  `;

  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${spaceGrotesk.variable} ${instrumentSerif.variable} antialiased`}>
        <Script id="bootstrap-auth-cleanup" strategy="beforeInteractive">
          {bootstrapAuthCleanupScript}
        </Script>
        <ThemeProvider>
          <SessionManager />
          {children}
          <ThemeToggleButton />
          <VidyaChat />
        </ThemeProvider>
      </body>
    </html>
  );
}
