"use client";

import { useContext, useEffect, useMemo, useTransition } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { UserSubscriptionPlan } from "@/types";

import { SubscriptionPlan } from "@/types/index";
import { pricingData } from "@/config/subscriptions";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { BillingFormButton } from "@/components/forms/billing-form-button";
import { ModalContext } from "@/components/modals/providers";
import { HeaderSection } from "@/components/shared/header-section";
import { Icons } from "@/components/shared/icons";
import MaxWidthWrapper from "@/components/shared/max-width-wrapper";
import { generateUserStripe } from "@/actions/generate-user-stripe";

interface PricingCardsProps {
  userId?: string;
  subscriptionPlan?: UserSubscriptionPlan;
}

export function PricingCards({ userId, subscriptionPlan }: PricingCardsProps) {
  const { setShowSignInModal } = useContext(ModalContext);
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isAutoCheckoutPending, startAutoCheckout] = useTransition();

  const buyPriceId = useMemo(() => {
    const raw = searchParams?.get("buy");
    return raw ? raw.trim() : null;
  }, [searchParams]);

  const buyPlan = useMemo(() => {
    const raw = searchParams?.get("plan");
    return raw ? raw.trim().toLowerCase() : null;
  }, [searchParams]);

  useEffect(() => {
    const priceIdFromUrl = buyPriceId;
    const priceIdFromPlan =
      buyPlan
        ? pricingData.find((p) => p.title.toLowerCase() === buyPlan)?.stripeIds
            .monthly ?? null
        : null;

    const priceId = priceIdFromUrl ?? priceIdFromPlan;
    if (!priceId) return;
    if (!userId) return;

    // Auto-start checkout after returning from OAuth. This will server-redirect to Stripe.
    startAutoCheckout(async () => {
      await generateUserStripe(priceId);
    });
  }, [buyPriceId, buyPlan, userId]);

  const PricingCard = ({ offer }: { offer: SubscriptionPlan }) => {
    return (
      <div
        className={cn(
          "relative flex flex-col overflow-hidden rounded-3xl border shadow-sm",
          offer.title.toLocaleLowerCase() === "pro"
            ? "-m-0.5 border-2 border-purple-400"
            : "",
        )}
        key={offer.title}
      >
        <div className="min-h-[150px] items-start space-y-4 bg-muted/50 p-6">
          <p className="flex font-urban text-sm font-bold uppercase tracking-wider text-muted-foreground">
            {offer.title}
          </p>

          <div className="flex flex-row">
            <div className="flex items-end">
              <div className="flex text-left text-3xl font-semibold leading-6">
                {`$${offer.prices.monthly}`}
              </div>
              <div className="-mb-1 ml-2 text-left text-sm font-medium text-muted-foreground">
                <div>/month</div>
              </div>
            </div>
          </div>
          <div className="text-left text-sm text-muted-foreground">
            when charged monthly
          </div>
        </div>

        <div className="flex h-full flex-col justify-between gap-16 p-6">
          <ul className="space-y-2 text-left text-sm font-medium leading-normal">
            {offer.benefits.map((feature) => (
              <li className="flex items-start gap-x-3" key={feature}>
                <Icons.check className="size-5 shrink-0 text-purple-500" />
                <p>{feature}</p>
              </li>
            ))}

            {offer.limitations.length > 0 &&
              offer.limitations.map((feature) => (
                <li
                  className="flex items-start text-muted-foreground"
                  key={feature}
                >
                  <Icons.close className="mr-3 size-5 shrink-0" />
                  <p>{feature}</p>
                </li>
              ))}
          </ul>

          {userId && subscriptionPlan ? (
            subscriptionPlan.isPaid ? (
              // User has a subscription - show manage/upgrade
              <BillingFormButton year={false} offer={offer} subscriptionPlan={subscriptionPlan} />
            ) : (
              // User doesn't have a subscription - show purchase button
              <BillingFormButton year={false} offer={offer} subscriptionPlan={subscriptionPlan} />
            )
          ) : (
            <Button
              variant={offer.title.toLocaleLowerCase() === "creator" ? "default" : "outline"}
              rounded="full"
              onClick={() => {
                const priceId = offer.stripeIds.monthly;
                const plan = offer.title.toLowerCase();
                // Carry purchase intent through auth redirect:
                // /login -> Google OAuth -> /pricing?buy=<priceId> -> auto checkout
                if (priceId) {
                  const qs = new URLSearchParams({
                    from: "/pricing",
                    buy: priceId,
                  });
                  router.push(`/login?${qs.toString()}`);
                  return;
                }

                // Fallback: carry plan intent (creator/studio) so auth flow still works,
                // and we can resolve to a price id after login (once env vars exist).
                const qs = new URLSearchParams({
                  from: "/pricing",
                  plan,
                });
                router.push(`/login?${qs.toString()}`);
              }}
            >
              Sign in to purchase
            </Button>
          )}
        </div>
      </div>
    );
  };

  return (
    <MaxWidthWrapper>
      <section className="flex flex-col items-center text-center">
        <HeaderSection
          label="Pricing"
          title="Paid plans (monthly minutes)"
          subtitle="Minutes are your monthly processing time. Need more? Buy rollover top-ups that carry over to future months."
        />

        {/* Monthly only for now */}

        <div className="grid gap-5 bg-inherit py-5 lg:grid-cols-3">
          {pricingData.map((offer) => (
            <PricingCard offer={offer} key={offer.title} />
          ))}
        </div>

        {isAutoCheckoutPending ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Redirecting you to checkout…
          </p>
        ) : null}

        <p className="mt-3 text-balance text-center text-base text-muted-foreground">
          Email{" "}
          <a
            className="font-medium text-primary hover:underline"
            href="mailto:support@videorecapai.com"
          >
            support@videorecapai.com
          </a>{" "}
          to contact our support team.
        </p>
      </section>
    </MaxWidthWrapper>
  );
}
