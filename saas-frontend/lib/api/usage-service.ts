/**
 * Usage Service
 * 
 * Tracks video processing usage for billing purposes.
 */

import { prisma } from "@/lib/db";
import { pricingData } from "@/config/subscriptions";

// Get current billing period in YYYY-MM format
function getCurrentBillingPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// Plan limits in minutes
const PLAN_LIMITS: Record<string, number> = {
  creator: 60,
  studio: 180,
};

/**
 * Record usage for a completed video job
 */
export async function recordUsage(
  userId: string,
  videoJobId: string,
  durationSeconds: number
): Promise<void> {
  const minutesUsed = durationSeconds / 60;
  const billingPeriod = getCurrentBillingPeriod();

  // Idempotency: avoid double-recording usage if the backend retries the completion webhook.
  // Note: this relies on the DB unique index (video_job_id, billing_period) for race safety.
  const existing = await prisma.usageRecord.findFirst({
    where: { userId, videoJobId, billingPeriod },
    select: { id: true },
  });
  if (existing) {
    return;
  }
  try {
    await prisma.usageRecord.create({
      data: {
        userId,
        videoJobId,
        minutesUsed,
        billingPeriod,
      },
    });
  } catch (e: any) {
    // Best-effort: if another concurrent request created it, treat as success.
    // Prisma unique constraint violation: P2002
    if (e?.code === "P2002") {
      return;
    }
    throw e;
  }

  // Deduct overage from top-up credits (rollover minutes).
  // This is a best-effort approach; we also gate job creation on remaining quota.
  const usage = await getCurrentUsage(userId);
  const overage = usage.minutesUsed - usage.minutesLimit;
  if (overage > 0 && usage.topUpMinutesRemaining > 0) {
    let remainingToDeduct = Math.ceil(overage);
    const credits = await prisma.topUpCredit.findMany({
      where: { userId, minutesRemaining: { gt: 0 } },
      orderBy: { createdAt: "asc" },
    });

    for (const credit of credits) {
      if (remainingToDeduct <= 0) break;
      const deduct = Math.min(credit.minutesRemaining, remainingToDeduct);
      remainingToDeduct -= deduct;
      await prisma.topUpCredit.update({
        where: { id: credit.id },
        data: { minutesRemaining: credit.minutesRemaining - deduct },
      });
    }
  }
}

/**
 * Get usage for current billing period
 */
export async function getCurrentUsage(userId: string): Promise<{
  minutesUsed: number;
  minutesLimit: number;
  topUpMinutesRemaining: number;
  totalAvailableMinutes: number;
  percentUsed: number;
  billingPeriod: string;
}> {
  const billingPeriod = getCurrentBillingPeriod();

  // Get total usage for this period
  const result = await prisma.usageRecord.aggregate({
    where: {
      userId,
      billingPeriod,
    },
    _sum: {
      minutesUsed: true,
    },
  });

  const minutesUsed = result._sum.minutesUsed || 0;

  // Get user's plan to determine limit
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { stripePriceId: true },
  });

  // Determine plan tier from price ID
  const planTier = getPlanTierFromPriceId(user?.stripePriceId);
  const minutesLimit = PLAN_LIMITS[planTier] || 0;

  const topUpAgg = await prisma.topUpCredit.aggregate({
    where: { userId },
    _sum: { minutesRemaining: true },
  });

  const topUpMinutesRemaining = topUpAgg._sum.minutesRemaining || 0;
  const totalAvailableMinutes = minutesLimit + topUpMinutesRemaining;

  const rawPercentUsed =
    totalAvailableMinutes <= 0 ? 0 : (minutesUsed / totalAvailableMinutes) * 100;
  const percentUsed = Math.min(100, Math.max(0, Math.round(rawPercentUsed)));

  return {
    minutesUsed: Math.round(minutesUsed * 100) / 100,
    minutesLimit,
    topUpMinutesRemaining,
    totalAvailableMinutes,
    // UI Progress expects 0-100; clamp to avoid invalid values (e.g., after overage).
    percentUsed,
    billingPeriod,
  };
}

/**
 * Check if user has remaining usage quota
 */
export async function hasRemainingQuota(userId: string, requiredMinutes = 1): Promise<boolean> {
  const usage = await getCurrentUsage(userId);
  
  return usage.minutesUsed + requiredMinutes <= usage.totalAvailableMinutes;
}

/**
 * Get usage history for the last N months
 */
export async function getUsageHistory(
  userId: string,
  months = 6
): Promise<Array<{ period: string; minutesUsed: number }>> {
  const history: Array<{ period: string; minutesUsed: number }> = [];
  const now = new Date();

  for (let i = 0; i < months; i++) {
    const date = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const period = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;

    const result = await prisma.usageRecord.aggregate({
      where: {
        userId,
        billingPeriod: period,
      },
      _sum: {
        minutesUsed: true,
      },
    });

    history.push({
      period,
      minutesUsed: Math.round((result._sum.minutesUsed || 0) * 100) / 100,
    });
  }

  return history.reverse();
}

/**
 * Get plan tier from Stripe price ID
 */
function getPlanTierFromPriceId(priceId: string | null | undefined): string {
  if (!priceId) return "none";

  // Check against configured price IDs
  for (const plan of pricingData) {
    if (plan.stripeIds.monthly === priceId || plan.stripeIds.yearly === priceId) {
      return plan.title.toLowerCase();
    }
  }

  return "none";
}

/**
 * Get detailed usage breakdown for billing
 */
export async function getUsageBreakdown(userId: string, billingPeriod?: string): Promise<{
  totalMinutes: number;
  jobCount: number;
  jobs: Array<{
    id: string;
    title: string | null;
    minutes: number;
    createdAt: Date;
  }>;
}> {
  const period = billingPeriod || getCurrentBillingPeriod();

  const records = await prisma.usageRecord.findMany({
    where: {
      userId,
      billingPeriod: period,
    },
    include: {
      // Note: This requires a relation from UsageRecord to VideoJob
      // For now, we'll fetch job details separately
    },
  });

  // Get job details for each usage record
  const jobIds = records
    .map((r) => r.videoJobId)
    .filter((id): id is string => id !== null);

  const jobs = await prisma.videoJob.findMany({
    where: {
      id: { in: jobIds },
    },
    select: {
      id: true,
      title: true,
      durationSeconds: true,
      createdAt: true,
    },
  });

  const jobMap = new Map(jobs.map((j) => [j.id, j]));

  return {
    totalMinutes: records.reduce((sum, r) => sum + r.minutesUsed, 0),
    jobCount: records.length,
    jobs: records.map((r) => {
      const job = r.videoJobId ? jobMap.get(r.videoJobId) : null;
      return {
        id: r.videoJobId || r.id,
        title: job?.title || "Unknown",
        minutes: r.minutesUsed,
        createdAt: r.createdAt,
      };
    }),
  };
}

