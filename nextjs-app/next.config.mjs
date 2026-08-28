/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
await import("./src/env.mjs");

/** @type {import("next").NextConfig} */
const config = {
  reactStrictMode: true,

  i18n: {
    locales: ["en"],
    defaultLocale: "en",
  },

  async rewrites() {
    const backend = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
      {
        source: '/predictGrid',
        destination: `${backend}/predictGrid`,
      },
      {
        source: '/roster',
        destination: `${backend}/roster`,
      },
    ];
  },
};
export default config;
