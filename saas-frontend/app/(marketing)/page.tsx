import { constructMetadata } from "@/lib/utils";
import { infos } from "@/config/landing";
import BentoGrid from "@/components/sections/bentogrid";
import Features from "@/components/sections/features";
import HeroLanding from "@/components/sections/hero-landing";
import InfoLanding from "@/components/sections/info-landing";
import Powered from "@/components/sections/powered";
import PreviewLanding from "@/components/sections/preview-landing";
import Testimonials from "@/components/sections/testimonials";
import { FaqSchema } from "@/components/seo/faq-schema";
import { ProductJsonLd } from "@/components/seo/jsonld";
import { siteConfig } from "@/config/site";

const faqItems = [
  {
    question: "Who is Video Recap AI for?",
    answer:
      "Anime recap YouTubers, movie/TV recap channels, TikTok/Shorts editors, and faceless creators who want to publish consistently but are stuck on scripting, clipping, voiceover sync, and copyright risk.",
  },
  {
    question: "What do I get after uploading an episode or movie?",
    answer:
      "A recap-ready package: a structured script, voiceover, and a suggested clip map you can export and refine in your editor.",
  },
  {
    question: "Will this prevent copyright claims?",
    answer:
      "No tool can guarantee zero claims. Video Recap AI includes optional copyright-safe editing patterns designed to reduce risk and improve consistency across uploads.",
  },
];

export const metadata = constructMetadata({
  title: "Video Recap AI – Anime & Movie Recap Automation",
  description:
    "Publish anime & movie recaps faster with AI: structured script, voiceover, and a clip map—plus optional copyright-safe editing patterns to reduce claim risk.",
  pathname: "/",
});

export default function IndexPage() {
  return (
    <>
      <ProductJsonLd
        pageUrl={`${siteConfig.url}/`}
        description="AI video recap tool for anime and movie recap creators. Generates a structured recap script, optional voiceover, and a clip map with timestamps."
      />
      <FaqSchema items={faqItems} />
      <HeroLanding />
      <section id="how-it-works" className="border-t py-10 md:py-14">
        <div className="container max-w-5xl">
          <h2 className="font-urban text-3xl font-bold tracking-tight">
            How it works
          </h2>
          <p className="mt-3 max-w-3xl text-balance text-muted-foreground">
            Drop a long video and get structured outputs you can lift directly
            into your editor—no more stitching tools together.
          </p>
          <div className="mt-6 grid gap-6 md:grid-cols-3">
            <div className="rounded-xl border bg-card p-5">
              <h3 className="font-semibold">1) Upload</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Add an episode or movie (plus an optional narration script).
              </p>
            </div>
            <div className="rounded-xl border bg-card p-5">
              <h3 className="font-semibold">2) Generate</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Get a recap script, voiceover (optional), and a clip map tied to
                timestamps.
              </p>
            </div>
            <div className="rounded-xl border bg-card p-5">
              <h3 className="font-semibold">3) Edit faster</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Use the outputs as a repeatable pipeline for every episode.
              </p>
            </div>
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            Next: see{" "}
            <a
              href="/pricing"
              className="font-medium underline underline-offset-4 hover:text-foreground"
            >
              Pricing
            </a>{" "}
            or read{" "}
            <a
              href="/docs"
              className="font-medium underline underline-offset-4 hover:text-foreground"
            >
              Documentation
            </a>
            .
          </p>

          <div className="mt-8 rounded-xl border bg-muted/30 p-5">
            <p className="text-sm text-muted-foreground">
              Primary use case:{" "}
              <span className="font-medium text-foreground">
                anime & movie recap creators
              </span>
              . We’ll be publishing deeper workflows and examples—start with{" "}
              <a
                href="/guides"
                className="font-medium underline underline-offset-4 hover:text-foreground"
              >
                Guides
              </a>
              .
            </p>
          </div>
        </div>
      </section>
      <PreviewLanding />
      <Powered />
      <BentoGrid />
      <InfoLanding data={infos[0]} reverse={true} />
      {/* <InfoLanding data={infos[1]} /> */}
      <Features />
      <Testimonials />
      <section id="faq" className="border-t py-10 md:py-14">
        <div className="container max-w-5xl">
          <h2 className="font-urban text-3xl font-bold tracking-tight">FAQ</h2>
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            {faqItems.map((item) => (
              <div key={item.question} className="rounded-xl border bg-card p-5">
                <h3 className="font-semibold">{item.question}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{item.answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
