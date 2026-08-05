import type { NextConfig } from "next";
import path from "path";

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-site" },
];

const nextConfig: NextConfig = {
  output: 'standalone',
  // Lets a verification build write somewhere other than the `.next` a running
  // server is serving from. Rebuilding in place swaps `.next/static` for new
  // content hashes while the live server keeps emitting HTML that references the
  // old ones, so every stylesheet 500s and the page renders unstyled. Set
  // NEXT_DIST_DIR to build without disturbing a running instance.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  outputFileTracingRoot: path.join(__dirname, ".."),
  skipTrailingSlashRedirect: true,
  allowedDevOrigins: ["127.0.0.1", "localhost", "web.test"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
    ],
  },
};

export default nextConfig;
