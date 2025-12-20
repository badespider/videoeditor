import React from "react";

type FaqItem = {
  question: string;
  answer: string;
};

/**
 * Renders FAQPage JSON-LD for SEO.
 * https://schema.org/FAQPage
 */
export function FaqSchema({
  items,
}: {
  items: FaqItem[];
}) {
  if (!items?.length) return null;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: item.answer,
      },
    })),
  };

  return (
    <script
      type="application/ld+json"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}


