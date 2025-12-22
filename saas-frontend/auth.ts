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
    error: "/login", // Redirect errors to login page instead of default error page
  },
  // Enable debug logging to diagnose issues
  debug: true,
  // Log all events for debugging
  events: {
    async signIn(message) {
      console.log("[auth][event] signIn", JSON.stringify(message));
    },
    async signOut(message) {
      console.log("[auth][event] signOut", JSON.stringify(message));
    },
    async createUser(message) {
      console.log("[auth][event] createUser", JSON.stringify(message));
    },
    async linkAccount(message) {
      console.log("[auth][event] linkAccount", JSON.stringify(message));
    },
    async session(message) {
      console.log("[auth][event] session", JSON.stringify(message));
    },
  },
  // Handle errors explicitly
  logger: {
    error(code, ...message) {
      console.error("[auth][error]", code, JSON.stringify(message));
    },
    warn(code, ...message) {
      console.warn("[auth][warn]", code, JSON.stringify(message));
    },
    debug(code, ...message) {
      console.log("[auth][debug]", code, JSON.stringify(message));
    },
  },
  // Explicit cookie configuration for production HTTPS
  // NOTE: Do NOT force secure cookies in local HTTP development, otherwise
  // OAuth/session cookies won't be set and sign-in will fail.
  // (Google callback typically ends in /login?error=Configuration or PKCE/state errors.)
  cookies: {
    sessionToken: {
      name: `authjs.session-token`,
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
    callbackUrl: {
      name: `authjs.callback-url`,
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
    csrfToken: {
      name: `authjs.csrf-token`,
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
    // Nonce cookie - critical for OAuth verification
    nonce: {
      name: `authjs.nonce`,
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
  },
  callbacks: {
    async signIn({ user, account, profile }) {
      console.log("[auth] signIn callback", { 
        userId: user?.id, 
        email: user?.email,
        provider: account?.provider 
      });
      // Allow all sign-ins
      return true;
    },

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

    async jwt({ token, user, account }) {
      // On initial sign in, user and account are available
      if (user) {
        console.log("[auth] jwt callback - initial sign in", { userId: user.id, email: user.email });
        token.id = user.id;
      }

      if (!token.sub) return token;

      try {
      const dbUser = await getUserById(token.sub);
        if (!dbUser) {
          console.log("[auth] jwt callback - user not found in db", { sub: token.sub });
          return token;
        }

      token.name = dbUser.name;
      token.email = dbUser.email;
      token.picture = dbUser.image;
      token.role = dbUser.role;
      } catch (error) {
        console.error("[auth] jwt callback error", error);
      }

      return token;
    },
  },
});
