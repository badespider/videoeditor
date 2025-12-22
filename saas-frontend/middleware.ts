import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";

const APP_HOST = "app.videorecapai.com";
const SITE_HOST = "videorecapai.com";
const WWW_SITE_HOST = "www.videorecapai.com";

function isMarketingRoute(pathname: string) {
  // Keep this conservative: only routes that should live on the marketing site.
  return (
    pathname === "/" ||
    pathname.startsWith("/pricing") ||
    pathname.startsWith("/blog") ||
    pathname.startsWith("/docs") ||
    pathname.startsWith("/guides") ||
    pathname.startsWith("/terms") ||
    pathname.startsWith("/privacy")
  );
}

function redirectPreviewToApp(req: NextRequest) {
  const host = req.headers.get("host") ?? "";
  const isProd = process.env.NODE_ENV === "production";

  // Fix PKCE issues caused by starting OAuth on the Vercel preview domain
  // and receiving the callback on the custom domain (cookies won't match).
  if (isProd && host.endsWith(".vercel.app") && host !== APP_HOST) {
    const url = req.nextUrl.clone();
    url.protocol = "https:";
    url.host = APP_HOST;
    return NextResponse.redirect(url, 308);
  }

  return null;
}

export default auth((req) => {
  const isProd = process.env.NODE_ENV === "production";
  const redirected = redirectPreviewToApp(req);
  if (redirected) return redirected;

  // Domain routing behavior:
  // - videorecapai.com (and www) should show marketing pages
  // - app.videorecapai.com should be the authenticated app
  //
  // Keep local/dev behavior unchanged (single host).
  if (isProd) {
    const host = (req.headers.get("host") ?? "").toLowerCase();
    const { pathname } = req.nextUrl;

    // If someone hits app.* for marketing pages, bounce them into the app.
    if (host === APP_HOST && isMarketingRoute(pathname)) {
      const url = req.nextUrl.clone();
      url.pathname = req.auth ? "/dashboard" : "/login";
      url.search = "";
      return NextResponse.redirect(url, 307);
    }

    // If someone hits the apex/www domain for app routes, bounce them to app.*.
    if ((host === SITE_HOST || host === WWW_SITE_HOST) && (pathname.startsWith("/dashboard") || pathname.startsWith("/admin") || pathname.startsWith("/login") || pathname.startsWith("/register"))) {
      const url = req.nextUrl.clone();
      url.protocol = "https:";
      url.host = APP_HOST;
      return NextResponse.redirect(url, 307);
    }
  }

  const { pathname } = req.nextUrl;
  const isProtected = pathname.startsWith("/dashboard") || pathname.startsWith("/admin");

  // Only protect app/admin pages. Do not gate `/api/auth/*` or marketing/docs/blog routes.
  if (!isProtected) return NextResponse.next();

  if (!req.auth) {
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};