// White-box source-presence guard (anti-rename canary) — NOT a behavior test. Each assertion only
// proves a turn-rewind wiring symbol still exists in the source; green does NOT prove rewind works at
// runtime (that needs a black-box smoke driving the button → runtime action).
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

assert.match(turnRewind, /planTurnRewind/, "`planTurnRewind` present in turnRewind.ts");
assert.match(button, /turnRewindConfirm/, "`turnRewindConfirm` present in TurnRewindButton.tsx");
assert.match(
  conversation,
  /TurnRewindButton/,
  "`TurnRewindButton` present in ConversationTurn.tsx",
);
assert.match(thread, /onTurnRewind/, "`onTurnRewind` present in Thread.tsx");
assert.match(app, /onTurnRewind/, "`onTurnRewind` present in App.tsx");

console.log("turn-rewind source-presence smoke passed");
