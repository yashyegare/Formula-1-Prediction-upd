import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      // Tests import via relative paths, but keep the alias available in case
      // production code grows '@/' imports.
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    include: ['tests/**/*.test.{ts,tsx}'],
    // Default: Node — fast, enough for the scoring engine, reducers and selectors.
    environment: 'node',
    environmentMatchGlobs: [
      // Browser-flavored tests (localStorage, fetch, React DOM) get jsdom.
      ['tests/**/*.dom.test.tsx', 'jsdom'],
      ['tests/**/*.dom.test.ts', 'jsdom'],
    ],
    globals: false,
    setupFiles: ['tests/setup.ts'],
    // No additional globals shimmed; jsdom tests stub fetch per-file.
  },
});
