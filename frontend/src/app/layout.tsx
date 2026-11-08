import type { Metadata } from "next";
import { headers } from "next/headers";
import localFont from "next/font/local";
import "./globals.css";
import { ThemeProvider } from "@/context/ThemeContext";
import VidyaChat from "@/components/VidyaChat";
import SessionManager from "@/components/SessionManager";
import ThemeToggleButton from "@/components/ThemeToggleButton";
import NonceStyleRuntime from "@/components/NonceStyleRuntime";

const spaceGrotesk = localFont({
  src: "../fonts/space-grotesk-latin.woff2",
  variable: "--font-sans",
  display: "swap",
  weight: "300 700",
});

const instrumentSerif = localFont({
  src: [
    { path: "../fonts/instrument-serif-latin.woff2", weight: "400", style: "normal" },
    { path: "../fonts/instrument-serif-latin-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-serif",
  display: "swap",
});

export const metadata: Metadata = {
  applicationName: "VidyaVerse",
  title: {
    default: "VidyaVerse - Student Opportunity Intelligence",
    template: "%s | VidyaVerse",
  },
  description:
    "Discover verified internships, jobs, hackathons, competitions, and workshops matched to your student profile.",
  keywords: [
    "student opportunities",
    "internships",
    "graduate jobs",
    "hackathons",
    "competitions",
    "career recommendations",
  ],
  category: "education",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: "/icon.svg",
  },
  openGraph: {
    type: "website",
    siteName: "VidyaVerse",
    title: "VidyaVerse - Student Opportunity Intelligence",
    description:
      "A verified, continuously refreshed opportunity network for students.",
  },
  twitter: {
    card: "summary",
    title: "VidyaVerse - Student Opportunity Intelligence",
    description:
      "A verified, continuously refreshed opportunity network for students.",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const nonce = (await headers()).get("x-nonce") || "";
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${spaceGrotesk.variable} ${instrumentSerif.variable} antialiased`}>
        <ThemeProvider>
          <NonceStyleRuntime nonce={nonce} />
          <SessionManager />
          {children}
          <ThemeToggleButton />
          <VidyaChat />
        </ThemeProvider>
      </body>
    </html>
  );
}
