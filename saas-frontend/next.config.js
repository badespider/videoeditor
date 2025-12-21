const { withContentlayer } = require("next-contentlayer2");

import("./env.mjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next.js 16 defaults to Turbopack in some scenarios; `next-contentlayer2`
  // relies on webpack hooks. Force-disable turbo to avoid "Turbopack + webpack"
  // config conflicts during Vercel builds.
  experimental: {
    turbo: false,
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
    turbopack: {},
};

module.exports = withContentlayer(nextConfig);
