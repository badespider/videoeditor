/**
 * API Route: /api/usage
 * 
 * Returns the current user's usage and quota information.
 */

import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getCurrentUsage } from "@/lib/api/usage-service";
import { getUserSubscriptionPlan } from "@/lib/subscription";

export async function GET() {
  try {
    const session = await auth();
    
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const [usage, subscription] = await Promise.all([
      getCurrentUsage(session.user.id),
      getUserSubscriptionPlan(session.user.id),
    ]);

    return NextResponse.json({
      minutesUsed: usage.minutesUsed,
      minutesLimit: usage.minutesLimit,
      topUpMinutesRemaining: usage.topUpMinutesRemaining,
      totalAvailableMinutes: usage.totalAvailableMinutes,
      percentUsed: usage.percentUsed,
      billingPeriod: usage.billingPeriod,
      isPaid: subscription.isPaid,
      planTier: subscription.title?.toLowerCase() || "none",
    });
  } catch (error) {
    console.error("Usage API error:", error);
    return NextResponse.json(
      { error: "Failed to fetch usage" },
      { status: 500 }
    );
  }
}


