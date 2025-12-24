import { NavBar } from "@/components/layout/navbar";
import { SiteFooter } from "@/components/layout/site-footer";
import { NavMobile } from "@/components/layout/mobile-nav";
import { SiteJsonLd } from "@/components/seo/jsonld";

interface MarketingLayoutProps {
  children: React.ReactNode;
}

export default function MarketingLayout({ children }: MarketingLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteJsonLd />
      <NavMobile />
      <NavBar scroll={true} />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
