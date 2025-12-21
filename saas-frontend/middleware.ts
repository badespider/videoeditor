import { NextResponse, type NextRequest } from "next/server";

import { auth } from "@/auth";

const APP_HOST = "app.videorecapai.com";

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
  const redirected = redirectPreviewToApp(req);
  if (redirected) return redirected;

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