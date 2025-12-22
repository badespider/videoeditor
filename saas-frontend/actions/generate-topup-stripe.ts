"use server";

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { stripe } from "@/lib/stripe";
import { getUserSubscriptionPlan } from "@/lib/subscription";
import { absoluteUrl } from "@/lib/utils";

const billingUrl = absoluteUrl("/dashboard/billing");

export async function generateTopupStripe(priceId: string, minutes: 60 | 120) {
  const session = await auth();
  const user = session?.user;

  if (!user || !user.email || !user.id) {
    throw new Error("Unauthorized");
  }

  const subscriptionPlan = await getUserSubscriptionPlan(user.id);
  if (!subscriptionPlan.isPaid) {
    throw new Error("Payment required: subscribe before buying top-ups.");
  }

  const stripeSession = await stripe.checkout.sessions.create({
    success_url: billingUrl,
    cancel_url: billingUrl,
    payment_method_types: ["card"],
    mode: "payment",
    billing_address_collection: "auto",
    customer: subscriptionPlan.stripeCustomerId ?? undefined,
    customer_email: subscriptionPlan.stripeCustomerId ? undefined : user.email,
    line_items: [{ price: priceId, quantity: 1 }],
    metadata: {
      userId: user.id,
      kind: "topup",
      // Safety: makes webhook crediting independent of price-id mapping.
      minutes: String(minutes),
    },
  });

  redirect(stripeSession.url as string);
}

