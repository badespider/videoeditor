"use client";

import Script from "next/script";
import { Analytics as VercelAnalytics } from "@vercel/analytics/react";

import { env } from "@/env.mjs";

const GA_MEASUREMENT_ID = env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
const ENABLE_VERCEL_ANALYTICS = process.env.NEXT_PUBLIC_VERCEL_ANALYTICS === "true";

export function Analytics() {
  return (
    <>
      {/* Prevent noisy 404s unless analytics is enabled on the Vercel project */}
      {ENABLE_VERCEL_ANALYTICS && <VercelAnalytics />}
      {GA_MEASUREMENT_ID && (
        <>
          <Script
            src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
            strategy="afterInteractive"
          />
          <Script id="google-analytics" strategy="afterInteractive">
            {`
              window.dataLayer = window.dataLayer || [];
              function gtag(){dataLayer.push(arguments);}
              gtag('js', new Date());
              gtag('config', '${GA_MEASUREMENT_ID}', {
                page_path: window.location.pathname,
              });
            `}
          </Script>
        </>
      )}
    </>
  );
}
