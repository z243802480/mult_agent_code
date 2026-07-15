// White-box source-presence guard (anti-rename canary) — NOT a behavior test. Each assertion only
// proves a side-chat wiring symbol still exists in the source; green does NOT prove side chat works at
// runtime (that needs a black-box smoke driving the panel/server).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerSurface } from "./server-surface.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const keyboard = readFileSync(path.join(root, "src/hooks/useStudioKeyboard.ts"), "utf8");
const sideChat = readFileSync(path.join(root, "src/features/sidechat/SideChatPanel.tsx"), "utf8");
const sideUtils = readFileSync(path.join(root, "src/features/sidechat/sideChatUtils.ts"), "utf8");
const server = readServerSurface(root);
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
const thread = readFileSync(path.join(root, "src/features/thread/Thread.tsx"), "utf8");

assert.match(
  keyboard,
  /Semicolon|key === ";"/,
  "`Semicolon` Ctrl+; binding present in useStudioKeyboard.ts",
);
// Assert the structural dock class, not the visible label. This used to read /Quick ask/, which
// went red the moment the UI was localized (the copy is now "快速提问") even though nothing about the
// side-chat wiring broke — a false alarm. The className is what the rest of the surface targets.
assert.match(sideChat, /sideChatDock/, "`sideChatDock` class present in SideChatPanel.tsx");
assert.match(
  sideUtils,
  /display_level === "side"/,
  '`display_level === "side"` present in sideChatUtils.ts',
);
assert.match(server, /channel === "side"/, '`channel === "side"` present in server surface');
assert.match(app, /sendSideAsk/, "`sendSideAsk` present in App.tsx");
assert.match(
  thread,
  /display_level === "main"/,
  '`display_level === "main"` present in Thread.tsx',
);

console.log("side-chat source-presence smoke passed");
