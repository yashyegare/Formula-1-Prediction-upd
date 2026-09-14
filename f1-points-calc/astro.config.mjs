import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  output: 'static',
  trailingSlash: 'never',
  // Emit flat files (about.html) rather than directory-style (about/index.html).
  // The static host serves clean URLs (/2017 -> 2017.html) via vercel.json's
  // cleanUrls on Vercel — keeping extensionless URLs consistent with
  // trailingSlash:'never' across the sitemap and canonicals.
  build: { format: 'file' },
  site: 'https://formula-1-prediction-upd-fxzg.vercel.app',
  integrations: [
    react(),
    tailwind(),
    sitemap({
      changefreq: 'weekly',
      priority: 1.0,
      lastmod: new Date(),
    }),
  ],
  vite: {
    build: {
      chunkSizeWarningLimit: 500,
    },
    server: {
      proxy: {
        '/user': {
          target: 'http://localhost:52313',
          changeOrigin: true,
        },
        '/leaderboard': {
          target: 'http://localhost:52313',
          changeOrigin: true,
        },
        // Blog is SSR'd by the worker (covers /blog, /blog/:slug, /blog/widgets.js)
        '/blog': {
          target: 'http://localhost:52313',
          changeOrigin: true,
        },
        '/sitemap-blog.xml': {
          target: 'http://localhost:52313',
          changeOrigin: true,
        },
      },
    },
  },
});
