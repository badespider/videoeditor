import authConfig from "@/auth.config";
import { PrismaAdapter } from "@auth/prisma-adapter";
import { UserRole } from "@prisma/client";
import NextAuth, { type DefaultSession } from "next-auth";

import { prisma } from "@/lib/db";
import { getUserById } from "@/lib/user";

const authSecret = process.env.AUTH_SECRET;
if (process.env.NODE_ENV === "production" && !authSecret) {
  // If AUTH_SECRET is missing, Auth.js can generate a new secret per invocation.
  // That breaks PKCE/state cookie parsing between /signin and /callback and yields:
  // "InvalidCheck: pkceCodeVerifier value could not be parsed"
  throw new Error("AUTH_SECRET is required in production.");
}

// More info: https://authjs.dev/getting-started/typescript#module-augmentation
declare module "next-auth" {
  interface Session {
    user: {
      role: UserRole;
    } & DefaultSession["user"];
  }
}

// Determine if we're in production (HTTPS)
const useSecureCookies = process.env.NODE_ENV === "production";
const cookiePrefix = useSecureCookies ? "__Secure-" : "";

export const {
  handlers: { GET, POST },
  auth,
} = NextAuth({
  // Spread authConfig first so our settings below take precedence
  ...authConfig,
  // Vercel + custom domains are behind a proxy; trust the host headers
  trustHost: true,
  // Ensure all invocations use the same secret (prevents PKCE/state parse failures)
  secret: authSecret,
  adapter: PrismaAdapter(prisma),
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
    // error: "/auth/error",
  },
  // Configure cookies to work with OAuth redirects
  // The PKCE cookie must use sameSite: "none" to survive the cross-site redirect from Google
  cookies: {
    pkceCodeVerifier: {
      name: `${cookiePrefix}authjs.pkce.code_verifier`,
      options: {
        httpOnly: true,
        sameSite: "none", // Required for cross-site OAuth redirects
        path: "/",
        secure: useSecureCookies,
        maxAge: 60 * 15, // 15 minutes
      },
    },
    state: {
      name: `${cookiePrefix}authjs.state`,
      options: {
        httpOnly: true,
        sameSite: "none", // Required for cross-site OAuth redirects  
        path: "/",
        secure: useSecureCookies,
        maxAge: 60 * 15, // 15 minutes
      },
    },
  },
  // Enable debug logging to diagnose PKCE issues
  debug: true,
  callbacks: {
    async session({ token, session }) {
      if (session.user) {
        if (token.sub) {
          session.user.id = token.sub;
        }

        if (token.email) {
          session.user.email = token.email;
        }

        if (token.role) {
          session.user.role = token.role;
        }

        session.user.name = token.name;
        session.user.image = token.picture;
      }

      return session;
    },

    async jwt({ token }) {
      if (!token.sub) return token;

      const dbUser = await getUserById(token.sub);

      if (!dbUser) return token;

      token.name = dbUser.name;
      token.email = dbUser.email;
      token.picture = dbUser.image;
      token.role = dbUser.role;

      return token;
    },
  },
});
