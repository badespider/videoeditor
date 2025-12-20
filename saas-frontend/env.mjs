import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    // This is optional because it's only used in development.
    // See https://next-auth.js.org/deployment.
    NEXTAUTH_URL: z.string().url().optional(),
    AUTH_SECRET: z.string().min(1).optional(),
    GOOGLE_CLIENT_ID: z.string().min(1).optional(),
    GOOGLE_CLIENT_SECRET: z.string().min(1).optional(),
    GITHUB_OAUTH_TOKEN: z.string().min(1).optional(),
    DATABASE_URL: z.string().min(1).optional(),
    RESEND_API_KEY: z.string().min(1).optional(),
    EMAIL_FROM: z.string().min(1).optional(),
    STRIPE_API_KEY: z.string().min(1).optional(),
    STRIPE_WEBHOOK_SECRET: z.string().min(1).optional(),
  },
  client: {
    NEXT_PUBLIC_APP_URL: z.string().min(1),
    // Canonical URL for SEO / OG tags (e.g., https://www.videorecapai.com)
    // Keep separate from NEXT_PUBLIC_APP_URL which may be localhost in development.
    NEXT_PUBLIC_SITE_URL: z.string().url().optional(),
    NEXT_PUBLIC_API_URL: z.string().url().optional(),
    // Subscriptions
    NEXT_PUBLIC_STRIPE_CREATOR_MONTHLY_PLAN_ID: z.string().min(1).optional(),
    NEXT_PUBLIC_STRIPE_STUDIO_MONTHLY_PLAN_ID: z.string().min(1).optional(),

    // One-time top-ups (rollover credits)
    NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID: z.string().min(1).optional(),
    NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID: z.string().min(1).optional(),
  },
  runtimeEnv: {
    NEXTAUTH_URL: process.env.NEXTAUTH_URL,
    AUTH_SECRET: process.env.AUTH_SECRET,
    GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET,
    GITHUB_OAUTH_TOKEN: process.env.GITHUB_OAUTH_TOKEN,
    DATABASE_URL: process.env.DATABASE_URL,
    RESEND_API_KEY: process.env.RESEND_API_KEY,
    EMAIL_FROM: process.env.EMAIL_FROM,
    NEXT_PUBLIC_APP_URL: process.env.NEXT_PUBLIC_APP_URL,
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
    // Video Editor API
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    // Stripe
    STRIPE_API_KEY: process.env.STRIPE_API_KEY,
    STRIPE_WEBHOOK_SECRET: process.env.STRIPE_WEBHOOK_SECRET,
    NEXT_PUBLIC_STRIPE_CREATOR_MONTHLY_PLAN_ID:
      process.env.NEXT_PUBLIC_STRIPE_CREATOR_MONTHLY_PLAN_ID,
    NEXT_PUBLIC_STRIPE_STUDIO_MONTHLY_PLAN_ID:
      process.env.NEXT_PUBLIC_STRIPE_STUDIO_MONTHLY_PLAN_ID,
    NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID:
      process.env.NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID,
    NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID:
      process.env.NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID,
  },
});
