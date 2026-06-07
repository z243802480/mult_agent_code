import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const turnDiff = readFileSync(path.join(root, "src/turnDiff.ts"), "utf8");
const diffPanel = readFileSync(path.join(root, "src/components/DiffScopePanel.tsx"), "utf8");
const diffToolbar = readFileSync(path.join(root, "src/features/inspector/diff/DiffScopeToolbar.tsx"), "utf8");
const diffFileList = readFileSync(path.join(root, "src/features/inspector/diff/DiffFileList.tsx"), "utf8");
const diffReview = readFileSync(path.join(root, "src/features/inspector/DiffReviewPane.tsx"), "utf8");
const conversationTurn = readFileSync(path.join(root, "src/features/thread/ConversationTurn.tsx"), "utf8");
const thread = readFileSync(path.join(root, "src/features/thread/Thread.tsx"), "utf8");
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
const workspaceReview = readFileSync(path.join(root, "src/session/useWorkspaceReview.ts"), "utf8");

assert.match(turnDiff, /reverse\(\)/, "turn scopes must be newest-first like Claude /diff");
assert.match(diffPanel, /DiffScopeToolbar/, "DiffScopePanel must compose scope toolbar");
assert.match(diffToolbar, /diffScopeTabs/, "DiffScopeToolbar must render scope tabs");
assert.match(diffFileList, /kind === "turn"/, "DiffFileList must support turn scope");
assert.match(diffReview, /diffReviewBody/, "DiffReviewPane must use split file/preview layout");
const diffPreview = readFileSync(path.join(root, "src/components/DiffPreview.tsx"), "utf8");
assert.match(diffPreview, /parseUnifiedDiff/, "DiffPreview must parse unified diff with line numbers");
assert.match(conversationTurn, /turnDiffButton/, "ConversationTurn must expose turn diff button");
assert.match(thread, /onTurnDiffSelect/, "Thread must wire turn diff selection");
assert.match(workspaceReview, /buildTurnDiffScopes/, "useWorkspaceReview must compute turn diff scopes");
assert.match(app, /onTurnDiffSelect|useWorkspaceReview/, "App must wire turn diff selection");

console.log("turn-diff-scope smoke passed");
