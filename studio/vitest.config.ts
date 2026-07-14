import { defineConfig } from "vitest/config";

// Unit tests only: src/**/*.test.ts(x). The Playwright specs under scripts/ (*.spec.mjs) drive a
// real browser against a real server and must NOT be collected here — vitest would try to run them
// as unit tests and fail on `test.beforeAll`.
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
