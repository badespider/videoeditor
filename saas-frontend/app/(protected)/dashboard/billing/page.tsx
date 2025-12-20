import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/session";
import { getUserSubscriptionPlan } from "@/lib/subscription";
import { prisma } from "@/lib/db";
import { env } from "@/env.mjs";
import { generateTopupStripe } from "@/actions/generate-topup-stripe";
import { constructMetadata } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { DashboardHeader } from "@/components/dashboard/header";
import { BillingInfo } from "@/components/pricing/billing-info";
import { Icons } from "@/components/shared/icons";

export const metadata = constructMetadata({
  title: "Billing – Video Recap AI",
  description: "Manage billing, minutes, and top-ups.",
});

// Plan limits in minutes
const PLAN_LIMITS: Record<string, number> = {
  creator: 60,
  studio: 180,
};

export default async function BillingPage() {
  const user = await getCurrentUser();

  let userSubscriptionPlan;
  if (user && user.id && user.role === "USER") {
    userSubscriptionPlan = await getUserSubscriptionPlan(user.id);
  } else {
    redirect("/login");
  }

  // Get current month's usage
  const currentMonth = new Date().toISOString().slice(0, 7); // YYYY-MM
  const usageResult = await prisma.usageRecord.aggregate({
    where: {
      userId: user.id,
      billingPeriod: currentMonth,
    },
    _sum: {
      minutesUsed: true,
    },
  });

  const minutesUsed = Math.round((usageResult._sum.minutesUsed || 0) * 100) / 100;
  const planName = userSubscriptionPlan?.title?.toLowerCase() || "creator";
  const minutesLimit = PLAN_LIMITS[planName] || PLAN_LIMITS.creator;
  const percentUsed = minutesLimit <= 0 ? 0 : Math.min(Math.round((minutesUsed / minutesLimit) * 100), 100);

  const topUpAgg = await prisma.topUpCredit.aggregate({
    where: { userId: user.id },
    _sum: { minutesRemaining: true },
  });
  const topUpMinutesRemaining = topUpAgg._sum.minutesRemaining || 0;
  const totalAvailableMinutes = minutesLimit + topUpMinutesRemaining;
  const totalRemainingMinutes = Math.max(0, totalAvailableMinutes - minutesUsed);

  return (
    <>
      <DashboardHeader
        heading="Billing"
        text="Manage billing and your subscription plan."
      />
      <div className="grid gap-8">
        {/* Usage Card */}
        <Card>
          <CardHeader>
            <CardTitle>Usage This Month</CardTitle>
            <CardDescription>
              Your video processing usage for {new Date().toLocaleDateString("en-US", { month: "long", year: "numeric" })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-2xl font-bold">{minutesUsed} min</span>
              <span className="text-muted-foreground">
                of {minutesLimit} plan min + {topUpMinutesRemaining} top-up min
              </span>
            </div>
            <Progress value={percentUsed} className="h-3" />
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>{percentUsed}% used</span>
              <span>{totalRemainingMinutes.toFixed(1)} min remaining</span>
            </div>
            {percentUsed >= 80 && (
              <Alert>
                <Icons.warning className="h-4 w-4" />
                <AlertTitle>Usage Warning</AlertTitle>
                <AlertDescription>
                  You&apos;ve used {percentUsed}% of your monthly quota. Consider upgrading your plan.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        {/* Top-ups */}
        <Card>
          <CardHeader>
            <CardTitle>Top-ups (rollover)</CardTitle>
            <CardDescription>
              Need more minutes this month? Buy additional minutes that roll over across months.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row">
            <form
              action={async () => {
                "use server";
                if (!env.NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID) {
                  throw new Error("Missing NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID");
                }
                await generateTopupStripe(env.NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID);
              }}
            >
              <button className="inline-flex h-10 items-center justify-center rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground">
                +60 min ($20)
              </button>
            </form>
            <form
              action={async () => {
                "use server";
                if (!env.NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID) {
                  throw new Error("Missing NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID");
                }
                await generateTopupStripe(env.NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID);
              }}
            >
              <button className="inline-flex h-10 items-center justify-center rounded-full border px-5 text-sm font-medium">
                +120 min ($40)
              </button>
            </form>
          </CardContent>
        </Card>

        {/* Stripe Test Mode Notice */}
        <Alert className="!pl-14">
          <Icons.warning />
          <AlertTitle>Test Mode</AlertTitle>
          <AlertDescription className="text-balance">
            This app is using Stripe test environment. You can find a list of test card numbers on the{" "}
            <a
              href="https://stripe.com/docs/testing#cards"
              target="_blank"
              rel="noreferrer"
              className="font-medium underline underline-offset-8"
            >
              Stripe docs
            </a>
            .
          </AlertDescription>
        </Alert>

        {/* Billing Info */}
        <BillingInfo userSubscriptionPlan={userSubscriptionPlan} />
      </div>
    </>
  );
}
