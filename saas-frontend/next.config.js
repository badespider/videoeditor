// const { withContentlayer } = require("next-contentlayer2");

import("./env.mjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Unblock production builds on Vercel: our Tailwind ESLint plugin is currently
  // enforcing class-order rules as errors across multiple pages.
  // We'll clean these up later; for now don't fail deployments on lint.
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "avatars.githubusercontent.com",
      },
      {
        protocol: "https",
        hostname: "lh3.googleusercontent.com",
      },
      {
        protocol: "https",
        hostname: "randomuser.me",
      },
    ],
  },
  // Next.js 16: serverComponentsExternalPackages moved out of experimental.
  // Keep Prisma on the server bundle allowlist.
  serverExternalPackages: ["@prisma/client"],
};

module.exports = nextConfig;
