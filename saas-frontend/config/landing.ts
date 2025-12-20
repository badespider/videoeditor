import { FeatureLdg, InfoLdg, TestimonialType } from "types";

export const infos: InfoLdg[] = [
  {
    title: "Built for anime recap creators who need speed and consistency",
    description:
      "Stop gluing ChatGPT, ElevenLabs, and an editor together for every video. Video Recap AI turns an episode or movie into a recap-ready package: script, voiceover, and a clip map—plus built-in patterns designed to reduce claim/blocked risk.",
    image: "/_static/illustrations/work-from-home.jpg",
    list: [
      {
        title: "Drop episode → get a recap package",
        description:
          "Generate a structured recap script, narration, and suggested clip map so you can publish faster without burning out.",
        icon: "video",
      },
      {
        title: "Automation where it matters",
        description:
          "Script + voiceover + clip selection are the bottlenecks. We optimize the whole workflow—not just one step.",
        icon: "settings",
      },
      {
        title: "Copyright-safe editing patterns",
        description:
          "Clip length limits, spacing, overlays, and transforms (optional) to reduce the chance of claims/blocks when uploading anime and movie recaps.",
        icon: "warning",
      },
    ],
  },
  {
    title: "A predictable pipeline you can repeat every upload",
    description:
      "You shouldn’t have to reinvent your process each time. Use the same pipeline on every episode and tune it with simple settings as you grow.",
    image: "/_static/illustrations/work-from-home.jpg",
    list: [
      {
        title: "Takes you from raw episode to edit decisions",
        description:
          "Instead of cutting thousands of micro-clips manually, you get a starting cut plan that matches your narration.",
        icon: "search",
      },
      {
        title: "Designed for solo creators and small teams",
        description:
          "Optimize for time, repeatability, and fewer moving parts—so you can ship consistently.",
        icon: "laptop",
      },
      {
        title: "Tuned for narrative flow (around 1x speed)",
        description:
          "Maintain a natural viewing experience while sampling the episode across the whole chapter range.",
        icon: "play",
      },
    ],
  },
];

export const features: FeatureLdg[] = [
  {
    title: "Recap script generation",
    description:
      "Turn long episodes into a structured recap outline and narration-friendly script.",
    link: "/pricing",
    icon: "copy",
  },
  {
    title: "Voiceover + timing that stays aligned",
    description:
      "Generate voiceover and keep it synced to the clips—no more “everything is messed up”.",
    link: "/pricing",
    icon: "play",
  },
  {
    title: "AI clip matching (experimental)",
    description:
      "Match script segments to the right moments so the visuals actually reflect what the narration says.",
    link: "/pricing",
    icon: "search",
  },
  {
    title: "Copyright protection (experimental)",
    description:
      "Apply safe-editing patterns like clip splitting, spacing, and consistent transforms to reduce claim/blocked risk.",
    link: "/pricing",
    icon: "warning",
  },
  {
    title: "Export-ready workflow",
    description:
      "Get a predictable pipeline output you can take straight into your editor instead of starting from scratch.",
    link: "/docs",
    icon: "dashboard",
  },
  {
    title: "Repeatability and presets",
    description:
      "Save what works for your channel and run it every episode—faster publishing with less stress.",
    link: "/docs",
    icon: "settings",
  },
];

export const testimonials: TestimonialType[] = [
  {
    name: "Anime recap creator",
    job: "Solo YouTuber",
    image: "https://randomuser.me/api/portraits/men/1.jpg",
    review:
      "I used to spend a full day cutting clips and syncing AI voice. Now I start from a recap script + clip map and focus on pacing and style instead of busy work.",
  },
  {
    name: "Faceless editor",
    job: "TikTok / Shorts",
    image: "https://randomuser.me/api/portraits/women/2.jpg",
    review:
      "The workflow is the best part: drop the episode, get narration + clip suggestions, and iterate. I finally post consistently without burning out.",
  },
  {
    name: "Growth-plateaued channel",
    job: "Anime recap YouTube",
    image: "https://randomuser.me/api/portraits/men/3.jpg",
    review:
      "Copyright is always stressful. Having built-in safe-editing patterns and consistent transforms made uploads feel less like gambling.",
  },
  {
    name: "Tiny team",
    job: "2-person creator team",
    image: "https://randomuser.me/api/portraits/men/5.jpg",
    review:
      "We’re faster because the pipeline is repeatable. We don’t have to reinvent the process every episode anymore.",
  },
  {
    name: "AI-first creator",
    job: "Uses ChatGPT + ElevenLabs",
    image: "https://randomuser.me/api/portraits/women/6.jpg",
    review:
      "I already used AI tools, but stitching everything together was painful. This feels purpose-built for anime recap production.",
  },
  {
    name: "New recap channel",
    job: "Trying to post weekly",
    image: "https://randomuser.me/api/portraits/women/4.jpg",
    review:
      "The biggest win is time. I can finally publish consistently instead of spending 1–2 days on one video.",
  },
  {
    name: "Editor who hates micro-clips",
    job: "Part-time creator",
    image: "https://randomuser.me/api/portraits/men/9.jpg",
    review:
      "Cutting thousands of tiny clips was killing me. Starting from a generated clip plan is a game changer.",
  },
];
