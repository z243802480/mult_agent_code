import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const turnDiff = readFileSync(path.join(root, "src/turnDiff.ts"), "utf8");
const diffPanel = readFileSync(path.join(root, "src/components/DiffScopePanel.tsx"), "utf8");
const thread = readFileSync(path.join(root, "src/components/Thread.tsx"), "utf8");
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");

assert.match(turnDiff, /reverse\(\)/, "turn scopes must be newest-first like Claude /diff");
assert.match(diffPanel, /diffScopeTabs/, "DiffScopePanel must render scope tabs");
assert.match(diffPanel, /kind === "turn"/, "DiffScopePanel must support turn scope");
const diffPreview = readFileSync(path.join(root, "src/components/DiffPreview.tsx"), "utf8");
assert.match(diffPreview, /parseUnifiedDiff/, "DiffPreview must parse unified diff with line numbers");
assert.match(thread, /turnDiffButton/, "Thread must expose turn diff button");
assert.match(app, /buildTurnDiffScopes/, "App must compute turn diff scopes");
assert.match(app, /onTurnDiffSelect/, "App must wire turn diff selection");

console.log("turn-diff-scope smoke passed");
