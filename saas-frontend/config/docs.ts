import { DocsConfig } from "types";

export const docsConfig: DocsConfig = {
  mainNav: [
    {
      title: "Documentation",
      href: "/docs",
    },
    {
      title: "Guides",
      href: "/guides",
    },
  ],
  sidebarNav: [
    {
      title: "Getting Started",
      items: [
        {
          title: "Welcome",
          href: "/docs",
        },
        {
          title: "Getting Started",
          href: "/docs/getting-started",
        },
        {
          title: "Uploading a Video",
          href: "/docs/upload-video",
        },
      ],
    },
    {
      title: "Using Video Recap AI",
      items: [
        {
          title: "Understanding Output",
          href: "/docs/understanding-output",
        },
        {
          title: "Copyright Protection",
          href: "/docs/copyright-protection",
        },
        {
          title: "Billing & Minutes",
          href: "/docs/billing-minutes",
        },
        {
          title: "FAQ",
          href: "/docs/faq",
        },
      ],
    },
  ],
};
