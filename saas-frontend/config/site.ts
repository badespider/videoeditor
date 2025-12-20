import { SidebarNavItem, SiteConfig } from "types";
import { env } from "@/env.mjs";

const site_url = env.NEXT_PUBLIC_SITE_URL ?? env.NEXT_PUBLIC_APP_URL;

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
      { title: "About", href: "/docs" },
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
