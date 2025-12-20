export const BLOG_CATEGORIES: {
  title: string;
  slug: "news" | "education" | "workflow" | "copyright" | "guide" | "productivity";
  description: string;
}[] = [
  {
    title: "Workflow",
    slug: "workflow",
    description: "Optimize your recap creation workflow.",
  },
  {
    title: "Copyright",
    slug: "copyright",
    description: "Strategies for reducing copyright claims and blocks.",
  },
  {
    title: "Guide",
    slug: "guide",
    description: "Step-by-step guides for recap creators.",
  },
  {
    title: "Productivity",
    slug: "productivity",
    description: "Tips for creating more content without burnout.",
  },
  {
    title: "News",
    slug: "news",
    description: "Updates and announcements from Video Recap AI.",
  },
  {
    title: "Education",
    slug: "education",
    description: "Educational content for recap creators.",
  },
];

export const BLOG_AUTHORS = {
  videorecapai: {
    name: "Video Recap AI",
    image: "/_static/avatars/videorecapai.png",
    twitter: "videorecapai",
  },
  mickasmt: {
    name: "mickasmt",
    image: "/_static/avatars/mickasmt.png",
    twitter: "miickasmt",
  },
  shadcn: {
    name: "shadcn",
    image: "/_static/avatars/shadcn.jpeg",
    twitter: "shadcn",
  },
};
