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

export const metadata = constructMetadata({
  title: "Video Recap AI – Anime & Movie Recap Automation",
  description:
    "Video Recap AI helps recap creators publish faster for anime and movies: generate a structured recap script, voiceover, and suggested clip map—with optional copyright-safe editing patterns to reduce claims/blocks.",
  pathname: "/",
});

export default function IndexPage() {
  return (
    <>
      <FaqSchema
        items={[
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
        ]}
      />
      <HeroLanding />
      <PreviewLanding />
      <Powered />
      <BentoGrid />
      <InfoLanding data={infos[0]} reverse={true} />
      {/* <InfoLanding data={infos[1]} /> */}
      <Features />
      <Testimonials />
    </>
  );
}
