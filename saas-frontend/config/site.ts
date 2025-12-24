import { SidebarNavItem, SiteConfig } from "types";
import { env } from "@/env.mjs";

function normalizeBaseUrl(raw: string) {
  let url = raw.trim();
  // Add scheme if missing (e.g. "www.videorecapai.com")
  if (!/^https?:\/\//i.test(url)) {
    url = `https://${url}`;
  }
  // Force HTTPS (prevents canonical/OG/sitemap emitting http:// which can trigger SEO+security warnings)
  url = url.replace(/^http:\/\//i, "https://");
  // Strip trailing slash
  url = url.replace(/\/$/, "");
  return url;
}

const site_url = normalizeBaseUrl(
  env.NEXT_PUBLIC_SITE_URL ?? env.NEXT_PUBLIC_APP_URL,
);

if (process.env.NODE_ENV === "production") {
  // SEO canonical should be the marketing domain in prod.
  if (!env.NEXT_PUBLIC_SITE_URL) {
    console.warn(
      "[site] NEXT_PUBLIC_SITE_URL is not set in production; canonical URLs may be incorrect.",
    );
  }
}

export const siteConfig: SiteConfig = {
  name: "Video Recap AI",
  description:
    "Video recap automation for anime and movies: generate a structured recap script, voiceover, and suggested clip map—with optional copyright-safe editing patterns to reduce claims and blocks.",
  url: site_url,
  ogImage: `${site_url}/_static/og.jpg`,
  links: {
    twitter: "https://twitter.com/videorecapai",
    github: "https://github.com/videorecapai",
  },
  mailSupport: "support@videorecapai.com",
};

export const footerLinks: SidebarNavItem[] = [
  {
    title: "Company",
    items: [
      { title: "About", href: "/about" },
      { title: "Contact", href: "/contact" },
      { title: "Terms", href: "/terms" },
      { title: "Privacy", href: "/privacy" },
    ],
  },
  {
    title: "Product",
    items: [
      { title: "Pricing", href: "/pricing" },
      { title: "Dashboard", href: "/dashboard" },
      { title: "New Video", href: "/dashboard/jobs/new" },
    ],
  },
  {
    title: "Docs",
    items: [
      { title: "Documentation", href: "/docs" },
      { title: "Guides", href: "/guides" },
      { title: "Blog", href: "/blog" },
    ],
  },
];
