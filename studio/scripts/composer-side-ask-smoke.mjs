import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readServerSurface } from "./server-surface.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const composer = readFileSync(path.join(root, "src/components/Composer.tsx"), "utf8");
const sideChatHook = readFileSync(path.join(root, "src/hooks/useSideChat.ts"), "utf8");
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");
const server = readServerSurface(root);

assert.match(composer, /composerSideAskToggle/, "Composer must expose quick ask toggle");
assert.match(composer, /onSideAsk/, "Composer must route side ask sends");
assert.match(composer, /\/ask/, "Composer must support /ask slash");
assert.match(composer, /sideAskMode/, "Composer must style side ask mode");
assert.match(sideChatHook, /composerSideAsk/, "useSideChat must persist composer side ask");
assert.match(app, /composerSideAsk/, "App must wire composer side ask");
assert.match(server, /sideAskContextHint/, "server must enrich side ask with session context");

console.log("composer-side-ask smoke passed");
