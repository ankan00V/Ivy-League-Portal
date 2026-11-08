import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VidyaVerse - Student Opportunity Intelligence",
    short_name: "VidyaVerse",
    description:
      "Discover verified internships, jobs, hackathons, competitions, and workshops matched to your profile.",
    start_url: "/",
    display: "standalone",
    background_color: "#09090b",
    theme_color: "#fcd34d",
    categories: ["education", "productivity"],
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
    ],
  };
}
