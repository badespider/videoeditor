import { headers } from "next/headers";
import Stripe from "stripe";

import { env } from "@/env.mjs";
import { prisma } from "@/lib/db";
import { stripe } from "@/lib/stripe";

function topUpMinutesForPrice(priceId: string | null | undefined): number | null {
  if (!priceId) return null;
  if (priceId === env.NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID) return 60;
  if (priceId === env.NEXT_PUBLIC_STRIPE_TOPUP_120_PRICE_ID) return 120;
  return null;
}

export async function POST(req: Request) {
  const body = await req.text();
  const signature = (await headers()).get("Stripe-Signature") as string;

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      env.STRIPE_WEBHOOK_SECRET,
    );
  } catch (error) {
    return new Response(`Webhook Error: ${error.message}`, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;

    // Subscription checkout
    if (session.mode === "subscription") {
      // Retrieve the subscription details from Stripe.
      const subscription = await stripe.subscriptions.retrieve(
        session.subscription as string,
      );

      // Update the user stripe info in our database.
      // Since this is the initial subscription, we need to update
      // the subscription id and customer id.
      await prisma.user.update({
        where: {
          id: session?.metadata?.userId,
        },
        data: {
          stripeSubscriptionId: subscription.id,
          stripeCustomerId: subscription.customer as string,
          stripePriceId: subscription.items.data[0].price.id,
          stripeCurrentPeriodEnd: new Date(
            subscription.current_period_end * 1000,
          ),
        },
      });
    }

    // One-time top-up checkout
    if (session.mode === "payment" && session.metadata?.kind === "topup") {
      const lineItems = await stripe.checkout.sessions.listLineItems(session.id, {
        limit: 5,
      });
      const priceId = lineItems.data?.[0]?.price?.id ?? null;
      const minutes = topUpMinutesForPrice(priceId);
      if (!minutes) {
        return new Response("Unknown top-up price id", { status: 400 });
      }

      // Idempotent crediting using stripe checkout session id uniqueness
      await prisma.topUpCredit.create({
        data: {
          userId: session?.metadata?.userId,
          minutesPurchased: minutes,
          minutesRemaining: minutes,
          stripeCheckoutSessionId: session.id,
        },
      });
    }
  }

  if (event.type === "invoice.payment_succeeded") {
    const session = event.data.object as Stripe.Invoice;

    // If the billing reason is not subscription_create, it means the customer has updated their subscription.
    // If it is subscription_create, we don't need to update the subscription id and it will handle by the checkout.session.completed event.
    if (session.billing_reason != "subscription_create") {
      // Retrieve the subscription details from Stripe.
      const subscription = await stripe.subscriptions.retrieve(
        session.subscription as string,
      );

      // Update the price id and set the new period end.
      await prisma.user.update({
        where: {
          stripeSubscriptionId: subscription.id,
        },
        data: {
          stripePriceId: subscription.items.data[0].price.id,
          stripeCurrentPeriodEnd: new Date(
            subscription.current_period_end * 1000,
          ),
        },
      });
    }
  }

  return new Response(null, { status: 200 });
}
