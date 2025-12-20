import { PlansRow, SubscriptionPlan } from "types";
import { env } from "@/env.mjs";

export const pricingData: SubscriptionPlan[] = [
  {
    title: "Creator",
    description: "For solo recap creators",
    benefits: [
      "60 minutes of processing per month",
      "Script + voiceover generation",
      "AI clip matching (experimental)",
      "Copyright-safe editing patterns (optional)",
      "Email support",
    ],
    limitations: [
      "Standard queue priority",
      "No team features",
    ],
    prices: {
      monthly: 20,
      yearly: 0,
    },
    stripeIds: {
      monthly: env.NEXT_PUBLIC_STRIPE_CREATOR_MONTHLY_PLAN_ID,
      yearly: null,
    },
  },
  {
    title: "Studio",
    description: "For high-output channels",
    benefits: [
      "180 minutes of processing per month (3h)",
      "Everything in Creator",
      "Priority processing queue",
      "Priority support",
    ],
    limitations: [
      "No enterprise custom SLA (hidden for now)",
    ],
    prices: {
      monthly: 60,
      yearly: 0,
    },
    stripeIds: {
      monthly: env.NEXT_PUBLIC_STRIPE_STUDIO_MONTHLY_PLAN_ID,
      yearly: null,
    },
  },
];

export const plansColumns = [
  "creator",
  "studio",
] as const;

export const comparePlans: PlansRow[] = [
  {
    feature: "Monthly Processing Time",
    creator: "60 min",
    studio: "180 min (3h)",
    tooltip: "Total video processing time allowed per month.",
  },
  {
    feature: "AI Scene Detection",
    creator: "Advanced",
    studio: "Advanced",
    tooltip: "AI-powered automatic scene detection and segmentation.",
  },
  {
    feature: "Voice-Over Quality",
    creator: "Premium",
    studio: "Premium+",
    tooltip: "Quality of AI-generated voice-over narration.",
  },
  {
    feature: "AI Clip Matching",
    creator: true,
    studio: true,
    tooltip: "Intelligent matching of clips to script segments.",
  },
  {
    feature: "Copyright Protection",
    creator: true,
    studio: true,
    tooltip: "Visual transforms to avoid copyright detection.",
  },
  {
    feature: "Processing Priority",
    creator: "Standard",
    studio: "Priority",
    tooltip: "Queue priority for video processing jobs.",
  },
  {
    feature: "Support",
    creator: "Email",
    studio: "Priority",
  },
  {
    feature: "Team Members",
    creator: "1",
    studio: "1",
    tooltip: "Number of team members who can access the account.",
  },
  {
    feature: "Export Workflow",
    creator: "Recap package",
    studio: "Recap package",
    tooltip:
      "Export-ready outputs to help you move from episode to publishable recap faster.",
  },
  {
    feature: "Copyright-Safe Patterns",
    creator: true,
    studio: true,
    tooltip:
      "Patterns like clip splitting, spacing, overlays, and optional transforms to reduce claims/blocks risk.",
  },
  {
    feature: "Rollover Top-ups",
    creator: true,
    studio: true,
    tooltip:
      "Buy additional minutes ($20=60min, $40=120min). Unused top-up minutes roll over across months.",
  },
];
