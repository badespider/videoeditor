import Image from "next/image";
import Link from "next/link";

import { constructMetadata } from "@/lib/utils";

export const metadata = constructMetadata({
  title: "Page Not Found – Video Recap AI",
  description: "The page you're looking for doesn't exist. Browse our documentation, pricing, or head back to the homepage.",
  pathname: "/404",
  noIndex: true,
});

const popularLinks = [
  { title: "Homepage", href: "/", description: "Start from the beginning" },
  { title: "Pricing", href: "/pricing", description: "View our plans and pricing" },
  { title: "Documentation", href: "/docs", description: "Learn how to use Video Recap AI" },
  { title: "Blog", href: "/blog", description: "Read our latest articles" },
  { title: "Dashboard", href: "/dashboard", description: "Access your projects" },
];

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-16">
      <h1 className="text-6xl font-bold">404</h1>
      <Image
        src="/_static/illustrations/rocket-crashed.svg"
        alt="Page not found illustration"
        width={300}
        height={300}
        className="pointer-events-none mb-4 mt-6 dark:invert"
        priority
      />
      <h2 className="mb-2 text-balance text-center text-2xl font-semibold">
        Oops! Page not found
      </h2>
      <p className="mb-8 max-w-md text-balance text-center text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
        Try one of these links instead:
      </p>

      <div className="mb-8 grid w-full max-w-2xl gap-4 sm:grid-cols-2">
        {popularLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="group rounded-lg border bg-card p-4 transition-colors hover:border-primary hover:bg-accent"
          >
            <h3 className="font-medium group-hover:text-primary">
              {link.title}
            </h3>
            <p className="text-sm text-muted-foreground">{link.description}</p>
          </Link>
        ))}
      </div>

      <div className="flex flex-col items-center gap-4 sm:flex-row">
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-md bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Back to Homepage
        </Link>
        <Link
          href="mailto:support@videorecapai.com?subject=Broken Link Report"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-primary"
        >
          Report a broken link
        </Link>
      </div>
    </div>
  );
}
