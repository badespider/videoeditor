import { constructMetadata } from "@/lib/utils";
import { siteConfig } from "@/config/site";

export const metadata = constructMetadata({
  title: `Contact – ${siteConfig.name}`,
  description:
    "Contact Video Recap AI support for questions, bugs, or billing help. We typically respond within 1–2 business days.",
  pathname: "/contact",
});

export default function ContactPage() {
  return (
    <div className="container max-w-3xl py-10 md:py-14">
      <h1 className="font-urban text-4xl font-extrabold tracking-tight">
        Contact
      </h1>

      <p className="mt-4 text-balance text-lg text-muted-foreground">
        Need help with your recap workflow, billing, or a bug? Email us and
        we’ll get back to you.
      </p>

      <div className="mt-8 rounded-lg border bg-card p-6">
        <h2 className="text-lg font-semibold">Support</h2>
        <p className="mt-2 text-muted-foreground">
          Email{" "}
          <a
            href={`mailto:${siteConfig.mailSupport}`}
            className="font-medium underline underline-offset-4 hover:text-foreground"
          >
            {siteConfig.mailSupport}
          </a>
          .
        </p>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
          <li>
            Include your account email and the job ID (if your issue is related
            to processing).
          </li>
          <li>We typically respond within 1–2 business days.</li>
        </ul>
      </div>

      <p className="mt-6 text-sm text-muted-foreground">
        For product details, see <a className="underline underline-offset-4 hover:text-foreground" href="/pricing">Pricing</a> and{" "}
        <a className="underline underline-offset-4 hover:text-foreground" href="/docs">Documentation</a>.
      </p>
    </div>
  );
}

