import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/opportunities", "/internships-jobs"],
      disallow: [
        "/api/",
        "/applications",
        "/control/",
        "/dashboard",
        "/forgot-password",
        "/onboarding",
        "/profile",
        "/reset-password",
        "/social",
        "/verify-email",
      ],
    },
  };
}
