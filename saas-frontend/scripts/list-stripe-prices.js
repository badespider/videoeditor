/**
 * Lists Stripe Prices for the Stripe account+mode configured by STRIPE_API_KEY.
 *
 * Usage:
 *   cd saas-frontend
 *   node scripts/list-stripe-prices.js
 */

/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");
const Stripe = require("stripe");

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
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

async function main() {
  loadDotEnvIfPresent();

  const stripeKey = process.env.STRIPE_API_KEY;
  if (!stripeKey) throw new Error("Missing STRIPE_API_KEY");

  const stripe = new Stripe(stripeKey, { apiVersion: "2024-04-10" });

  const prices = [];
  let starting_after = undefined;

  // Pull up to 100 prices (2 pages of 50) - enough for most setups.
  for (let page = 0; page < 4; page++) {
    const resp = await stripe.prices.list({
      limit: 50,
      // NOTE: do not filter by `active` here — we want to see inactive prices too for debugging.
      starting_after,
      expand: ["data.product"],
    });
    prices.push(...resp.data);
    if (!resp.has_more) break;
    starting_after = resp.data[resp.data.length - 1]?.id;
    if (!starting_after) break;
  }

  const rows = prices
    // Show both one-time and recurring, so we can debug if top-ups were created as recurring by accident.
    .map((p) => ({
      id: p.id,
      type: p.recurring ? `recurring:${p.recurring.interval || "?"}` : "one_time",
      amount: p.unit_amount != null ? `${(p.unit_amount / 100).toFixed(2)}` : "",
      currency: (p.currency || "").toUpperCase(),
      nickname: p.nickname || "",
      product: typeof p.product === "object" ? (p.product?.name || "") : String(p.product || ""),
    }))
    .sort((a, b) => (a.product + a.nickname).localeCompare(b.product + b.nickname));

  console.log(`Found ${rows.length} prices (active + inactive; mode inferred from key).`);
  console.table(rows);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});


