import { MetadataRoute } from "next";
import { allDocs, allGuides, allPosts } from "contentlayer/generated";

import { siteConfig } from "@/config/site";

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = siteConfig.url;

  // Static marketing pages
  const staticPages: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${baseUrl}/about`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.4,
    },
    {
      url: `${baseUrl}/contact`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.4,
    },
    {
      url: `${baseUrl}/pricing`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/blog`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/docs`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/guides`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.7,
    },
    {
      url: `${baseUrl}/terms`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.3,
    },
    {
      url: `${baseUrl}/privacy`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.3,
    },
  ];

  // Blog posts
  const blogPosts: MetadataRoute.Sitemap = allPosts
    .filter((post) => post.published)
    .map((post) => ({
      url: `${baseUrl}${post.slug}`,
      lastModified: new Date(post.date),
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));

  // Documentation pages
  const docPages: MetadataRoute.Sitemap = allDocs
    .filter((doc) => doc.published)
    .map((doc) => ({
      url: `${baseUrl}${doc.slug}`,
      lastModified: new Date(),
      changeFrequency: "weekly" as const,
      priority: 0.7,
    }));

  // Guide pages
  const guidePages: MetadataRoute.Sitemap = allGuides
    .filter((guide) => guide.published)
    .map((guide) => ({
      url: `${baseUrl}${guide.slug}`,
      lastModified: new Date(guide.date),
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));

  return [...staticPages, ...blogPosts, ...docPages, ...guidePages];
}
