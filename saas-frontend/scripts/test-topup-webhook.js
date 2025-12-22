/**
 * End-to-end test for "buy minutes" (top-up) payments.
 *
 * What it does:
 * - Creates/ensures a test user in Prisma
 * - Creates a Stripe Checkout Session (mode=payment) for your top-up price
 * - Sends a SIGNED `checkout.session.completed` webhook event to your app
 * - Verifies TopUpCredit was created (minutes added)
 *
 * Usage:
 *   cd saas-frontend
 *   node scripts/test-topup-webhook.js
 *
 * Optional env:
 *   WEBHOOK_URL=https://app.videorecapai.com/api/webhooks/stripe
 *   TOPUP_PRICE_ID=price_...
 *   TEST_USER_EMAIL=test-topup@example.com
 *
 * Required env (can be in saas-frontend/.env; this script loads it):
 *   DATABASE_URL
 *   STRIPE_API_KEY
 *   STRIPE_WEBHOOK_SECRET
 *   NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID (or set TOPUP_PRICE_ID)
 */

/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const Stripe = require("stripe");
const { PrismaClient } = require("@prisma/client");

function loadDotEnvIfPresent() {
  const envPath = path.join(__dirname, "..", ".env");
  if (!fs.existsSync(envPath)) return;

  const raw = fs.readFileSync(envPath, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx < 0) continue;
    const key = trimmed.slice(0, idx).trim();
    let val = trimmed.slice(idx + 1).trim();
    // strip quotes
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

function requireEnv(name) {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var ${name}`);
  return v;
}

async function main() {
  loadDotEnvIfPresent();

  const dbUrl = requireEnv("DATABASE_URL");
  const stripeKey = requireEnv("STRIPE_API_KEY");
  const webhookSecret = requireEnv("STRIPE_WEBHOOK_SECRET");

  const priceId =
    process.env.TOPUP_PRICE_ID ||
    process.env.NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID ||
    null;

  if (!priceId) {
    throw new Error(
      "Missing TOPUP_PRICE_ID or NEXT_PUBLIC_STRIPE_TOPUP_60_PRICE_ID. Set one to your Stripe test-mode price id."
    );
  }

  const webhookUrl =
    process.env.WEBHOOK_URL ||
    (process.env.NEXT_PUBLIC_APP_URL
      ? `${process.env.NEXT_PUBLIC_APP_URL.replace(/\/$/, "")}/api/webhooks/stripe`
      : null);

  if (!webhookUrl) {
    throw new Error(
      "Missing WEBHOOK_URL (or NEXT_PUBLIC_APP_URL). Example: WEBHOOK_URL=https://app.videorecapai.com/api/webhooks/stripe"
    );
  }

  const testEmail = process.env.TEST_USER_EMAIL || `test-topup-${Date.now()}@example.com`;

  const prisma = new PrismaClient({ datasourceUrl: dbUrl });
  const stripe = new Stripe(stripeKey, { apiVersion: "2024-04-10" });

  console.log("🔧 Using webhook URL:", webhookUrl);
  console.log("🔧 Using top-up price:", priceId);
  console.log("🔧 Using test email:", testEmail);

  // 1) Ensure a user exists.
  const user = await prisma.user.upsert({
    where: { email: testEmail },
    update: {},
    create: {
      email: testEmail,
      name: "Test TopUp",
    },
    select: { id: true, email: true },
  });

  console.log("✅ Test user:", user.id);

  // 2) Create a checkout session (mode=payment) with metadata required by webhook handler.
  const session = await stripe.checkout.sessions.create({
    mode: "payment",
    payment_method_types: ["card"],
    customer_email: user.email || undefined,
    success_url: "https://example.com/success",
    cancel_url: "https://example.com/cancel",
    line_items: [{ price: priceId, quantity: 1 }],
    metadata: {
      userId: user.id,
      kind: "topup",
    },
  });

  console.log("✅ Created Stripe checkout session:", session.id);

  // 3) Build a checkout.session.completed event for THIS session.
  const event = {
    id: `evt_test_${crypto.randomBytes(8).toString("hex")}`,
    object: "event",
    api_version: "2024-04-10",
    created: Math.floor(Date.now() / 1000),
    data: { object: session },
    livemode: false,
    pending_webhooks: 1,
    request: { id: null, idempotency_key: null },
    type: "checkout.session.completed",
  };

  const payload = JSON.stringify(event);

  // Stripe library helper to create a valid signature header for tests.
  const signature = stripe.webhooks.generateTestHeaderString({
    payload,
    secret: webhookSecret,
  });

  // 4) POST to your webhook endpoint.
  const res = await fetch(webhookUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Stripe-Signature": signature,
    },
    body: payload,
  });

  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Webhook POST failed (${res.status}): ${text}`);
  }

  console.log("✅ Webhook accepted:", res.status);

  // 5) Verify we credited minutes (TopUpCredit created).
  const credit = await prisma.topUpCredit.findUnique({
    where: { stripeCheckoutSessionId: session.id },
  });

  if (!credit) {
    throw new Error("❌ Expected TopUpCredit record not found. Webhook likely misconfigured.");
  }

  console.log("✅ TopUpCredit created:", {
    minutesPurchased: credit.minutesPurchased,
    minutesRemaining: credit.minutesRemaining,
    userId: credit.userId,
    stripeCheckoutSessionId: credit.stripeCheckoutSessionId,
  });

  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});


