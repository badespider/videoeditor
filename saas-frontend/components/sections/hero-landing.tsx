import Link from "next/link";

import { siteConfig } from "@/config/site";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { Icons } from "@/components/shared/icons";

export default function HeroLanding() {
  return (
    <section id="top" className="space-y-6 py-12 sm:py-20 lg:py-20">
      <div className="container flex max-w-5xl flex-col items-center gap-5 text-center">
        <div
          className={cn(
            buttonVariants({ variant: "outline", size: "sm", rounded: "full" }),
            "px-4",
          )}
        >
          Built for recap creators: anime, movies, and TV
        </div>

        <h1 className="text-balance font-urban text-4xl font-extrabold tracking-tight sm:text-5xl md:text-6xl lg:text-[66px]">
          Make{" "}
          <span className="text-gradient_indigo-purple font-extrabold">
            video recap edits
          </span>
          {" "}in hours, not days.
        </h1>

        <p
          className="max-w-2xl text-balance leading-normal text-muted-foreground sm:text-xl sm:leading-8"
          style={{ animationDelay: "0.35s", animationFillMode: "forwards" }}
        >
          An AI video recap tool for anime and movie recap creators. Upload an episode or movie and get a recap-ready package: script, voiceover, and a clip map—with optional copyright-safe patterns.
        </p>

        <div
          className="flex justify-center space-x-2 md:space-x-4"
          style={{ animationDelay: "0.4s", animationFillMode: "forwards" }}
        >
          <Link
            href="/pricing"
            prefetch={true}
            className={cn(
              buttonVariants({ size: "lg", rounded: "full" }),
              "gap-2",
            )}
          >
            <span>See pricing</span>
            <Icons.arrowRight className="size-4" />
          </Link>
          <Link
            href="/docs"
            className={cn(
              buttonVariants({
                variant: "outline",
                size: "lg",
                rounded: "full",
              }),
              "px-5",
            )}
          >
            <Icons.bookOpen className="mr-2 size-4" />
            <p>See how it works</p>
          </Link>
        </div>
      </div>
    </section>
  );
}
