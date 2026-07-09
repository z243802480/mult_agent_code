import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const turnRewind = readFileSync(path.join(root, "src/features/thread/turnRewind.ts"), "utf8");
const button = readFileSync(path.join(root, "src/features/thread/TurnRewindButton.tsx"), "utf8");
const conversation = readFileSync(
  path.join(root, "src/features/thread/ConversationTurn.tsx"),
  "utf8",
);
const thread = readFileSync(path.join(root, "src/features/thread/Thread.tsx"), "utf8");
const app = readFileSync(path.join(root, "src/App.tsx"), "utf8");

assert.match(turnRewind, /planTurnRewind/, "turnRewind must plan runtime action");
assert.match(button, /turnRewindConfirm/, "TurnRewindButton must confirm before action");
assert.match(conversation, /TurnRewindButton/, "ConversationTurn must render rewind");
assert.match(thread, /onTurnRewind/, "Thread must wire turn rewind");
assert.match(app, /onTurnRewind/, "App must connect rewind to runtime action");

console.log("turn-rewind smoke passed");
