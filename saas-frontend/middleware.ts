export { auth as middleware } from "@/auth";

// IMPORTANT:
// Do NOT run auth middleware on `/api/auth/*` (OAuth/PKCE endpoints).
// Running middleware there can break the PKCE flow and cause:
// "InvalidCheck: pkceCodeVerifier value could not be parsed"
export const config = {
  matcher: ["/dashboard/:path*", "/admin/:path*"],
};