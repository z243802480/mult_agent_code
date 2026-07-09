// Flat ESLint config (ESLint 9) for Asteria Studio.
//
// Scope is deliberately split into two environments because this package mixes a
// browser React/TS app (`src/`) with a Node runtime (`server.mjs` + `scripts/*.mjs`).
// Type-aware linting is intentionally NOT enabled (no `parserOptions.project`): the
// recommended non-type-checked rules catch real bugs fast without a slow project
// service, which is the right first gate for a codebase that had none. Prettier owns
// formatting; `eslint-config-prettier` (last) disables every stylistic rule so the two
// tools never fight.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import unusedImports from "eslint-plugin-unused-imports";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "undefined/**", // junk dir from a legacy `"undefined"` path bug; ignored, slated for deletion
      "playwright-report/**",
      "test-results/**",
    ],
  },
  // Browser React + TypeScript source.
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "unused-imports": unusedImports,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // `any` is a smell but not a build-breaker; there is currently ~1 in src.
      "@typescript-eslint/no-explicit-any": "warn",
      // Dead imports are an auto-fixable error (removed by `eslint --fix`); dead locals
      // are a warning (removing them can change signatures / needs a human eye).
      "@typescript-eslint/no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
  // Node server + smoke/test scripts (plain ESM JS).
  {
    files: ["server.mjs", "scripts/**/*.mjs", "*.mjs", "*.js"],
    extends: [js.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
    plugins: {
      "unused-imports": unusedImports,
    },
    rules: {
      "no-unused-vars": "off",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
  // Shared rule tweaks across both environments.
  {
    rules: {
      // Empty catch blocks are an intentional idiom here (best-effort cleanup that must
      // never throw); other empty blocks still error.
      "no-empty": ["error", { allowEmptyCatch: true }],
      // Control chars in regex are intentional in the ANSI/`<think>` output sanitizers.
      "no-control-regex": "warn",
    },
  },
  prettier,
);
