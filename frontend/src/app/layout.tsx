import type { Metadata } from "next";
import { Space_Grotesk, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/context/ThemeContext";
import VidyaChat from "@/components/VidyaChat";

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
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${spaceGrotesk.variable} ${instrumentSerif.variable} antialiased`}>
        <ThemeProvider>
          {children}
          <VidyaChat />
        </ThemeProvider>
      </body>
    </html>
  );
}
