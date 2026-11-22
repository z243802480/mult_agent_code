import { defineConfig } from "vitest/config";

// Unit tests: src/**/*.test.ts(x) and lib/**/*.test.mjs. Playwright scripts/ (*.spec.mjs) drive a
// real browser against a real server and must NOT be collected here — vitest would try to run them
// as unit tests and fail on `test.beforeAll`.
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "lib/**/*.test.mjs"],
  },
});
