import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const keyboard = readFileSync(path.join(root, "src/hooks/useStudioKeyboard.ts"), "utf8");
const sideChat = readFileSync(path.join(root, "src/features/sidechat/SideChatPanel.tsx"), "utf8");
const sideUtils = readFileSync(path.join(root, "src/features/sidechat/sideChatUtils.ts"), "utf8");
const server = readFileSync(path.join(root, "server.mjs"), "utf8");
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
const thread = readFileSync(path.join(root, "src/features/thread/Thread.tsx"), "utf8");

assert.match(keyboard, /Semicolon|key === ";"/, "useStudioKeyboard must bind Ctrl+;");
assert.match(sideChat, /Quick ask/, "SideChatPanel must expose quick ask UI");
assert.match(sideUtils, /display_level === "side"/, "side chat events must use display_level side");
assert.match(server, /channel === "side"/, "server must route side channel to off-thread chat");
assert.match(app, /sendSideAsk/, "App must wire side ask send");
assert.match(thread, /display_level === "main"/, "Thread must keep side chat off main narrative");

console.log("side-chat smoke passed");
