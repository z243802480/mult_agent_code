import { defineConfig } from "@playwright/test";

// The UI specs had no config at all, so `npx playwright test <path>` resolved differently depending
// on the working directory (and could even pull a second, mismatched @playwright/test through npx —
// which fails with "did not expect test.beforeEach() to be called here"). Pinning testDir here makes
// `npm run test:ui` deterministic from anywhere, which is what lets CI run these at all.
export default defineConfig({
  testDir: "./scripts",
  testMatch: /.*\.spec\.mjs$/,
  // Each spec boots its own Studio server on a fixed port — they must not race each other.
  workers: 1,
  fullyParallel: false,
  reporter: process.env.CI ? "line" : "list",
  use: { baseURL: `http://127.0.0.1:${process.env.ASTERIA_STUDIO_INTERACTIVE_PORT || 18860}` },
});
