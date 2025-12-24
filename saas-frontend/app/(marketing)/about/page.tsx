import { constructMetadata } from "@/lib/utils";
import { siteConfig } from "@/config/site";

export const metadata = constructMetadata({
  title: `About – ${siteConfig.name}`,
  description:
    "Learn what Video Recap AI is, who it’s for, and how it helps anime and movie recap creators publish faster with a recap-ready package.",
  pathname: "/about",
});

export default function AboutPage() {
  return (
    <div className="container max-w-4xl py-10 md:py-14">
      <h1 className="font-urban text-4xl font-extrabold tracking-tight">
        About {siteConfig.name}
      </h1>

      <p className="mt-4 text-balance text-lg text-muted-foreground">
        {siteConfig.name} is an AI video recap tool built for creators who turn
        anime episodes, movies, and TV into recap videos. Our goal is simple:
        help you publish consistently by automating the slowest parts of the
        workflow.
      </p>

      <div className="mt-10 grid gap-8">
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">What it produces</h2>
          <p className="text-muted-foreground">
            When you upload a video, {siteConfig.name} generates a recap-ready
            package you can refine in your editor:
          </p>
          <ul className="list-disc space-y-2 pl-5 text-muted-foreground">
            <li>
              A structured recap script (intro, acts, climax, outro) optimized
              for narration
            </li>
            <li>Voiceover audio (optional)</li>
            <li>A suggested clip map with timestamps tied to the script</li>
            <li>
              Optional copyright-safe editing patterns designed to reduce claim
              risk (no guarantees)
            </li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Who it’s for</h2>
          <p className="text-muted-foreground">
            Solo YouTubers, faceless editors, and small teams producing anime,
            movie, and TV recap content—especially when script writing, clip
            selection, and narration sync are slowing down output.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Trust & policies</h2>
          <p className="text-muted-foreground">
            We keep pricing and policies clear so creators can evaluate the tool
            quickly. See{" "}
            <a
              href="/terms"
              className="font-medium underline underline-offset-4 hover:text-foreground"
            >
              Terms
            </a>{" "}
            and{" "}
            <a
              href="/privacy"
              className="font-medium underline underline-offset-4 hover:text-foreground"
            >
              Privacy
            </a>
            .
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Contact</h2>
          <p className="text-muted-foreground">
            Questions, bugs, or billing issues? Email{" "}
            <a
              href={`mailto:${siteConfig.mailSupport}`}
              className="font-medium underline underline-offset-4 hover:text-foreground"
            >
              {siteConfig.mailSupport}
            </a>
            . We typically respond within 1–2 business days.
          </p>
        </section>
      </div>
    </div>
  );
}

