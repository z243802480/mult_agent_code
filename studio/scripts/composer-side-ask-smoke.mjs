// White-box source-presence guard (anti-rename canary) — NOT a behavior test. Each assertion only
// proves a side-ask wiring symbol still exists in the source; green does NOT prove the composer
// side-ask flow works at runtime (that needs a black-box smoke driving the Composer/server).
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

assert.match(composer, /composerSideAskToggle/, "`composerSideAskToggle` present in Composer.tsx");
assert.match(composer, /onSideAsk/, "`onSideAsk` present in Composer.tsx");
assert.match(composer, /\/ask/, "`/ask` slash present in Composer.tsx");
assert.match(composer, /sideAskMode/, "`sideAskMode` present in Composer.tsx");
assert.match(sideChatHook, /composerSideAsk/, "`composerSideAsk` present in useSideChat.ts");
assert.match(app, /composerSideAsk/, "`composerSideAsk` present in App.tsx");
assert.match(server, /sideAskContextHint/, "`sideAskContextHint` present in server surface");

console.log("composer-side-ask source-presence smoke passed");
