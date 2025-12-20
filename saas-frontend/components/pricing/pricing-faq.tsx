import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

import { HeaderSection } from "../shared/header-section";
import { FaqSchema } from "@/components/seo/faq-schema";

export const pricingFaqData = [
  {
    id: "item-1",
    question: "Who is Video Recap AI for?",
    answer:
      "Anime recap YouTubers, movie/TV recap channels, TikTok/Shorts editors, and faceless creators who want to publish consistently but are stuck on scripting, clipping, voiceover sync, and copyright risk.",
  },
  {
    id: "item-2",
    question: "What does the pipeline output?",
    answer:
      "A recap-ready package: a structured recap script, voiceover, and a suggested clip map (what parts of the episode to use for each script segment). You can then export and refine in your editor.",
  },
  {
    id: "item-3",
    question: "Will this prevent copyright claims or blocks?",
    answer:
      "No tool can guarantee zero claims. Video Recap AI includes optional copyright-safe editing patterns (clip length limits, spacing, overlays, transforms) designed to reduce risk and make results more consistent across uploads.",
  },
  {
    id: "item-4",
    question: "How is this different from using ChatGPT + ElevenLabs + an editor?",
    answer:
      "Those tools are powerful, but most creators lose time stitching them together every episode. Video Recap AI is purpose-built for recap production: script, voiceover, clip matching, and optional safe-editing patterns in one repeatable pipeline.",
  },
  {
    id: "item-5",
    question: "How do billing minutes work?",
    answer:
      "Minutes are your monthly processing allowance (not your upload length). If you generate 60 minutes of output in a month, you’ve used 60 minutes. If you hit your limit, you can buy rollover top-ups (+60 min or +120 min) that persist across months.",
  },
];

export function PricingFaq() {
  return (
    <section className="container max-w-4xl py-2">
      <FaqSchema
        items={pricingFaqData.map((i) => ({ question: i.question, answer: i.answer }))}
      />
      <HeaderSection
        label="FAQ"
        title="Frequently asked by recap creators"
        subtitle="Short answers to the biggest questions: workflow, output, and copyright risk."
      />

      <Accordion type="single" collapsible className="my-12 w-full">
        {pricingFaqData.map((faqItem) => (
          <AccordionItem key={faqItem.id} value={faqItem.id}>
            <AccordionTrigger>{faqItem.question}</AccordionTrigger>
            <AccordionContent className="text-sm text-muted-foreground sm:text-[15px]">
              {faqItem.answer}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}
