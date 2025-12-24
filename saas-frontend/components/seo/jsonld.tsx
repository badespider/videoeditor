import * as React from "react";

import { siteConfig } from "@/config/site";

function JsonLd({ data }: { data: unknown }) {
  return (
    <script
      type="application/ld+json"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

/**
 * Organization + WebSite JSON-LD.
 * Helps LLMs and search engines understand who owns the site and what it is.
 */
export function SiteJsonLd() {
  const data = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${siteConfig.url}#organization`,
        name: siteConfig.name,
        url: siteConfig.url,
        logo: {
          "@type": "ImageObject",
          url: siteConfig.ogImage,
        },
        sameAs: [siteConfig.links.twitter, siteConfig.links.github].filter(Boolean),
        contactPoint: [
          {
            "@type": "ContactPoint",
            contactType: "customer support",
            email: siteConfig.mailSupport,
          },
        ],
      },
      {
        "@type": "WebSite",
        "@id": `${siteConfig.url}#website`,
        url: siteConfig.url,
        name: siteConfig.name,
        publisher: { "@id": `${siteConfig.url}#organization` },
      },
    ],
  };

  return <JsonLd data={data} />;
}

/**
 * Product JSON-LD for the core product.
 * Kept lightweight until we add richer real-world proof (case studies, reviews).
 */
export function ProductJsonLd({
  pageUrl,
  description,
}: {
  pageUrl: string;
  description: string;
}) {
  const data = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: siteConfig.name,
    applicationCategory: "VideoApplication",
    operatingSystem: "Web",
    url: pageUrl,
    description,
    offers: {
      "@type": "Offer",
      url: `${siteConfig.url}/pricing`,
      priceCurrency: "USD",
      // Intentionally omit price until we have final pricing copy we want to encode.
      availability: "https://schema.org/InStock",
    },
    publisher: { "@id": `${siteConfig.url}#organization` },
  };

  return <JsonLd data={data} />;
}

