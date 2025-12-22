/**
 * API Route: /api/backend/token
 *
 * Returns a short-lived JWT for calling the backend API directly from the browser.
 * This avoids Vercel function body-size limits for large video uploads.
 */

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getCurrentUsage } from "@/lib/api/usage-service";
import { getUserSubscriptionPlan } from "@/lib/subscription";
import { sign } from "jsonwebtoken";

const JWT_SECRET = process.env.AUTH_SECRET || "";

export async function GET() {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (!JWT_SECRET) {
      return NextResponse.json({ error: "Server misconfigured" }, { status: 500 });
    }

    const [subscriptionPlan, usage] = await Promise.all([
      getUserSubscriptionPlan(session.user.id),
      getCurrentUsage(session.user.id),
    ]);

    const remainingMinutes = usage.totalAvailableMinutes - usage.minutesUsed;

    if (usage.totalAvailableMinutes <= 0) {
      return NextResponse.json(
        {
          error: "payment_required",
          message: "You need minutes to process videos. Please buy minutes or subscribe.",
        },
        { status: 402 },
      );
    }

    if (remainingMinutes <= 0) {
      return NextResponse.json(
        {
          error: "quota_exceeded",
          message: "You have no minutes remaining. Buy a top-up to continue.",
          details: {
            minutesUsed: usage.minutesUsed,
            minutesLimit: usage.minutesLimit,
            topUpMinutesRemaining: usage.topUpMinutesRemaining,
            totalAvailableMinutes: usage.totalAvailableMinutes,
          },
        },
        { status: 402 },
      );
    }

    const subscriptionTier = subscriptionPlan.title?.toLowerCase() || "none";
    const planTier = subscriptionPlan.isPaid ? subscriptionTier : "topup";

    const token = sign(
      {
        sub: session.user.id,
        email: session.user.email,
        name: session.user.name,
        plan_tier: planTier,
        minutes_limit: usage.minutesLimit,
        minutes_used: usage.minutesUsed,
        minutes_remaining: remainingMinutes,
        // Backend quota gate uses minutes_remaining; keep this true if they can process.
        is_paid: remainingMinutes > 0,
      },
      JWT_SECRET,
      { expiresIn: "1h" },
    );

    return NextResponse.json({
      token,
      quota: {
        minutesRemaining: remainingMinutes,
        minutesUsed: usage.minutesUsed,
        totalAvailableMinutes: usage.totalAvailableMinutes,
        planTier,
        isPriority: subscriptionPlan.isPaid && subscriptionTier === "studio",
      },
    });
  } catch (error) {
    console.error("Backend token API error:", error);
    return NextResponse.json({ error: "Failed to create token" }, { status: 500 });
  }
}


