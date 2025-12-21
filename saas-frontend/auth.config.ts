import type { NextAuthConfig } from "next-auth";
import Google from "next-auth/providers/google";
import Resend from "next-auth/providers/resend";
import Credentials from "next-auth/providers/credentials";

import { env } from "@/env.mjs";
import { sendVerificationRequest } from "@/lib/email";
import { prisma } from "@/lib/db";

export default {
  providers: [
    ...(env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET
      ? [
          Google({
            clientId: env.GOOGLE_CLIENT_ID,
            clientSecret: env.GOOGLE_CLIENT_SECRET,
            // Use state-based verification instead of PKCE
            // PKCE cookies can fail on cross-site OAuth redirects in some browser configurations
            checks: ["state"],
          }),
        ]
      : []),
    ...(env.RESEND_API_KEY && env.EMAIL_FROM
      ? [
          Resend({
            apiKey: env.RESEND_API_KEY,
            from: env.EMAIL_FROM,
            // sendVerificationRequest,
          }),
        ]
      : []),
    // Dev-only credentials provider so you can run the app locally without OAuth/Resend setup.
    ...(process.env.NODE_ENV !== "production"
      ? [
          Credentials({
            id: "credentials",
            name: "Dev Login",
            credentials: {
              email: {
                label: "Email",
                type: "email",
                placeholder: "dev@example.com",
              },
            },
            async authorize(credentials) {
              const email = credentials?.email?.toString().trim().toLowerCase();
              if (!email) return null;

              // Upsert a local dev user so the PrismaAdapter/JWT callbacks can work normally.
              const user =
                (await prisma.user.findUnique({ where: { email } })) ??
                (await prisma.user.create({
                  data: {
                    email,
                    name: email.split("@")[0],
                    role: "USER",
                  },
                }));

              return {
                id: user.id,
                email: user.email,
                name: user.name,
                image: user.image,
                role: user.role,
              } as any;
            },
          }),
        ]
      : []),
  ],
} satisfies NextAuthConfig;
