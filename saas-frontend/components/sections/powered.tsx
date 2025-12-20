import { FileText, Mic, Film, Shield, Clock, Zap } from "lucide-react";

import MaxWidthWrapper from "@/components/shared/max-width-wrapper";

const deliverables = [
  {
    title: "Structured Script",
    description: "AI-generated recap script with intro, acts, climax, and outro",
    icon: FileText,
  },
  {
    title: "Voiceover Audio",
    description: "Ready-to-use narration synced to your script segments",
    icon: Mic,
  },
  {
    title: "Clip Map",
    description: "Suggested timestamps matching each script section",
    icon: Film,
  },
  {
    title: "Copyright Patterns",
    description: "Optional safe-editing transforms to reduce claim risk",
    icon: Shield,
  },
  {
    title: "Hours, Not Days",
    description: "Turn a 24-min episode into a recap package in under 2 hours",
    icon: Clock,
  },
  {
    title: "Repeatable Pipeline",
    description: "Same workflow every episode—no more starting from scratch",
    icon: Zap,
  },
];

export default function Powered() {
  return (
    <section className="py-14">
      <MaxWidthWrapper>
        <h2 className="text-center text-sm font-semibold uppercase text-muted-foreground">
          What You Get
        </h2>
        <p className="mx-auto mt-2 max-w-2xl text-center text-2xl font-bold tracking-tight sm:text-3xl">
          Everything you need to ship recaps faster
        </p>

        <div className="mt-10 grid grid-cols-2 gap-6 md:grid-cols-3">
          {deliverables.map((item) => (
            <div
              key={item.title}
              className="flex flex-col items-center rounded-xl border bg-card p-6 text-center shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-primary/10">
                <item.icon className="size-6 text-primary" />
              </div>
              <h3 className="font-semibold">{item.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {item.description}
              </p>
            </div>
          ))}
        </div>
      </MaxWidthWrapper>
    </section>
  );
}
